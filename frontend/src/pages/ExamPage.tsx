import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2, Send } from 'lucide-react'
import { Markdown } from '@/components/shared/Markdown'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useBatchSaveAnswers, useExamSession, useSubmitExam, useUploadHandwriting } from '@/hooks/useExam'
import { useExamStore } from '@/stores/useExamStore'
import { BubbleSheetCard } from '@/features/exam/components/BubbleSheetCard'
import { ExamTimer } from '@/features/exam/components/ExamTimer'
import { HandwritingBoard, type HandwritingBoardHandle } from '@/features/exam/components/HandwritingBoard'
import { QuestionNavigator } from '@/features/exam/components/QuestionNavigator'
import { SubmitConfirmDialog } from '@/features/exam/components/SubmitConfirmDialog'
import type { ExamQuestion, SaveExamAnswerRequest, StudentAnswer } from '@/types/exam'

function questionMode(question: ExamQuestion): 'single' | 'multi' | 'fill' | 'handwriting' {
  const raw = `${question.questionType || question.type || ''}`.toLowerCase()
  if (raw.includes('multi') || raw.includes('多选')) return 'multi'
  if (raw.includes('single') || raw.includes('choice') || raw.includes('选择') || raw.includes('单选')) return 'single'
  if (raw.includes('fill') || raw.includes('blank') || raw.includes('填空')) return 'fill'
  return 'handwriting'
}

function extractOptions(stem: string): string[] {
  const matches = Array.from(String(stem || '').matchAll(/[（(]?([A-F])[）).、]/gi)).map((m) => m[1].toUpperCase())
  const unique = Array.from(new Set(matches))
  return unique.length >= 2 ? unique.slice(0, 6) : ['A', 'B', 'C', 'D']
}

function answerFromStudent(answer?: StudentAnswer): SaveExamAnswerRequest | undefined {
  if (!answer) return undefined
  return {
    questionId: answer.questionId,
    questionType: answer.questionType,
    selectedOptions: answer.selectedOptions,
    fillBlankText: answer.fillBlankText,
    handwritingImagePath: answer.handwritingImagePath,
    textAnswer: answer.textAnswer,
  }
}

function isAnswered(answer?: SaveExamAnswerRequest): boolean {
  return Boolean(
    answer?.selectedOptions?.length ||
      answer?.fillBlankText?.trim() ||
      answer?.handwritingImagePath?.trim() ||
      answer?.textAnswer?.trim()
  )
}

export default function ExamPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const { data: session, isLoading, error } = useExamSession(sessionId, { includeAnswers: true })
  const batchSave = useBatchSaveAnswers(sessionId)
  const uploadHandwriting = useUploadHandwriting(sessionId)
  const submitExam = useSubmitExam()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const handwritingRef = useRef<HandwritingBoardHandle | null>(null)

  const store = useExamStore()
  const currentQuestion = session?.questions[store.currentQuestionIndex]

  useEffect(() => {
    if (!session || store.sessionId === session.sessionId) return
    store.setSession(session.sessionId, session.questions, session.expiresAt)
    for (const question of session.questions) {
      const existing = answerFromStudent(question.studentAnswer)
      if (existing) store.updateAnswer(question.questionId, existing)
    }
    store.markSaved(session.questions.map((q) => q.questionId))
  }, [session, store])

  useEffect(() => {
    if (!session || session.mode !== 'timed' || session.status !== 'in_progress') return
    const id = window.setInterval(() => {
      const remaining = store.tick(session.expiresAt)
      if (remaining === 0) {
        handleSubmit(true)
      }
    }, 1000)
    return () => window.clearInterval(id)
  })

  useEffect(() => {
    if (!session || session.status !== 'in_progress') return
    const id = window.setInterval(() => {
      saveDirty()
    }, 30_000)
    return () => window.clearInterval(id)
  })

  const answeredCount = useMemo(() => {
    if (!session) return 0
    return session.questions.filter((q) => isAnswered(store.answers[q.questionId] || answerFromStudent(q.studentAnswer))).length
  }, [session, store.answers])

  const saveDirty = async () => {
    const state = useExamStore.getState()
    if (!sessionId || !state.dirtyQuestionIds.length) return
    const payload = state.dirtyQuestionIds.map((qid) => state.answers[qid]).filter(Boolean)
    if (!payload.length) return
    state.setSaving(true)
    try {
      await batchSave.mutateAsync(payload)
      useExamStore.getState().markSaved(payload.map((x) => x.questionId))
    } finally {
      useExamStore.getState().setSaving(false)
    }
  }

  const saveCurrentHandwriting = async () => {
    if (!currentQuestion || questionMode(currentQuestion) !== 'handwriting') return
    await handwritingRef.current?.exportImage()
  }

  const handleSelectQuestion = async (index: number) => {
    await saveCurrentHandwriting()
    await saveDirty()
    store.setCurrentQuestionIndex(index)
  }

  const handleSubmit = async (fromTimer = false) => {
    if (!sessionId) return
    await saveCurrentHandwriting()
    await saveDirty()
    const result = await submitExam.mutateAsync(sessionId)
    setConfirmOpen(false)
    if (fromTimer || result.sessionId) navigate(`/exam/${sessionId}/result`)
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !session) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
        <div className="text-lg font-medium">考试会话不存在</div>
        <Button asChild variant="outline">
          <Link to="/papers">返回试卷</Link>
        </Button>
      </div>
    )
  }

  if (session.status !== 'in_progress') {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
        <div className="text-lg font-medium">本次作答已结束</div>
        <Button asChild>
          <Link to={`/exam/${session.sessionId}/result`}>查看成绩</Link>
        </Button>
      </div>
    )
  }

  const answer = currentQuestion ? store.answers[currentQuestion.questionId] || answerFromStudent(currentQuestion.studentAnswer) : undefined
  const mode = currentQuestion ? questionMode(currentQuestion) : 'single'

  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <Button asChild variant="ghost" size="icon">
            <Link to={`/papers/${session.paperId}`}>
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold">{session.paperName}</h1>
            <p className="text-xs text-muted-foreground">{answeredCount}/{session.questions.length} 已答</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {session.mode === 'timed' && <ExamTimer remainingSeconds={store.remainingSeconds} />}
          <Button type="button" onClick={() => setConfirmOpen(true)}>
            <Send className="h-4 w-4" />
            交卷
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <QuestionNavigator
          questions={session.questions}
          currentIndex={store.currentQuestionIndex}
          answers={store.answers}
          onSelect={handleSelectQuestion}
        />

        <main className="flex min-w-0 flex-1 flex-col">
          {currentQuestion && (
            <div className="flex-1 overflow-auto p-5 md:p-8">
              <div className="mx-auto max-w-3xl space-y-6">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium">第 {store.currentQuestionIndex + 1} 题</div>
                    <div className="text-xs text-muted-foreground">{currentQuestion.questionType || currentQuestion.type} · {currentQuestion.maxScore} 分</div>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {store.isSaving ? '保存中...' : store.lastSavedAt ? `已保存 ${store.lastSavedAt}` : '未保存'}
                  </div>
                </div>

                <section className="rounded-md border bg-card p-5">
                  <Markdown content={currentQuestion.stem || ''} />
                </section>

                {mode === 'single' || mode === 'multi' ? (
                  <BubbleSheetCard
                    mode={mode}
                    options={extractOptions(currentQuestion.stem)}
                    value={answer?.selectedOptions || []}
                    onChange={(selectedOptions) =>
                      store.updateAnswer(currentQuestion.questionId, {
                        questionId: currentQuestion.questionId,
                        questionType: currentQuestion.questionType,
                        selectedOptions,
                      })
                    }
                  />
                ) : mode === 'fill' ? (
                  <Input
                    value={answer?.fillBlankText || ''}
                    onChange={(event) =>
                      store.updateAnswer(currentQuestion.questionId, {
                        questionId: currentQuestion.questionId,
                        questionType: currentQuestion.questionType,
                        fillBlankText: event.target.value,
                      })
                    }
                    placeholder="输入答案"
                  />
                ) : (
                  <div className="space-y-3">
                    <HandwritingBoard
                      ref={handwritingRef}
                      imageUrl={currentQuestion.studentAnswer?.handwritingImageUrl}
                      onImageFile={async (file) => {
                        const uploaded = await uploadHandwriting.mutateAsync({ questionId: currentQuestion.questionId, file })
                        store.updateAnswer(currentQuestion.questionId, {
                          questionId: currentQuestion.questionId,
                          questionType: currentQuestion.questionType,
                          handwritingImagePath: uploaded.path,
                        })
                      }}
                    />
                    <Textarea
                      value={answer?.textAnswer || ''}
                      onChange={(event) =>
                        store.updateAnswer(currentQuestion.questionId, {
                          questionId: currentQuestion.questionId,
                          questionType: currentQuestion.questionType,
                          textAnswer: event.target.value,
                        })
                      }
                      placeholder="可选文字补充"
                      className="min-h-24"
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          <footer className="flex items-center justify-between border-t p-3">
            <Button
              type="button"
              variant="outline"
              disabled={store.currentQuestionIndex <= 0}
              onClick={() => handleSelectQuestion(store.currentQuestionIndex - 1)}
            >
              <ChevronLeft className="h-4 w-4" />
              上一题
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={store.currentQuestionIndex >= session.questions.length - 1}
              onClick={() => handleSelectQuestion(store.currentQuestionIndex + 1)}
            >
              下一题
              <ChevronRight className="h-4 w-4" />
            </Button>
          </footer>
        </main>
      </div>

      <SubmitConfirmDialog
        open={confirmOpen}
        answeredCount={answeredCount}
        totalCount={session.questions.length}
        isSubmitting={submitExam.isPending}
        onOpenChange={setConfirmOpen}
        onConfirm={() => handleSubmit(false)}
      />
    </div>
  )
}
