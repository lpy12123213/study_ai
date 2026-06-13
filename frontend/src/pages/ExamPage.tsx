import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2, Send, Sparkles } from 'lucide-react'
import { QuestionContent } from '@/components/shared/QuestionContent'
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
  const submitInFlightRef = useRef(false)
  const saveDirtyRef = useRef<() => Promise<void>>(async () => undefined)
  const handleSubmitRef = useRef<(fromTimer?: boolean) => Promise<void>>(async () => undefined)

  const storeSessionId = useExamStore((state) => state.sessionId)
  const currentQuestionIndex = useExamStore((state) => state.currentQuestionIndex)
  const answers = useExamStore((state) => state.answers)
  const remainingSeconds = useExamStore((state) => state.remainingSeconds)
  const isSaving = useExamStore((state) => state.isSaving)
  const lastSavedAt = useExamStore((state) => state.lastSavedAt)
  const setSession = useExamStore((state) => state.setSession)
  const updateAnswer = useExamStore((state) => state.updateAnswer)
  const markSaved = useExamStore((state) => state.markSaved)
  const setCurrentQuestionIndex = useExamStore((state) => state.setCurrentQuestionIndex)
  const currentQuestion = session?.questions[currentQuestionIndex]

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
    setCurrentQuestionIndex(index)
  }

  const handleSubmit = async (fromTimer = false) => {
    if (!sessionId || submitInFlightRef.current) return
    submitInFlightRef.current = true
    try {
      await saveCurrentHandwriting()
      await saveDirty()
      const result = await submitExam.mutateAsync(sessionId)
      setConfirmOpen(false)
      if (fromTimer || result.sessionId) navigate(`/exam/${sessionId}/result`)
    } catch (err) {
      submitInFlightRef.current = false
      throw err
    }
  }
  saveDirtyRef.current = saveDirty
  handleSubmitRef.current = handleSubmit

  useEffect(() => {
    if (!session || storeSessionId === session.sessionId) return
    setSession(session.sessionId, session.questions, session.expiresAt)
    for (const question of session.questions) {
      const existing = answerFromStudent(question.studentAnswer)
      if (existing) updateAnswer(question.questionId, existing)
    }
    markSaved(session.questions.map((q) => q.questionId))
  }, [markSaved, session, setSession, storeSessionId, updateAnswer])

  useEffect(() => {
    if (!session || session.mode !== 'timed' || session.status !== 'in_progress') return
    const id = window.setInterval(() => {
      const remaining = useExamStore.getState().tick(session.expiresAt)
      if (remaining === 0) {
        void handleSubmitRef.current(true)
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [session?.expiresAt, session?.mode, session?.status])

  useEffect(() => {
    if (!session || session.status !== 'in_progress') return
    const id = window.setInterval(() => {
      void saveDirtyRef.current()
    }, 30_000)
    return () => window.clearInterval(id)
  }, [session?.sessionId, session?.status])

  const answeredCount = useMemo(() => {
    if (!session) return 0
    return session.questions.filter((q) => isAnswered(answers[q.questionId] || answerFromStudent(q.studentAnswer))).length
  }, [answers, session])

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

  const answer = currentQuestion ? answers[currentQuestion.questionId] || answerFromStudent(currentQuestion.studentAnswer) : undefined
  const mode = currentQuestion ? questionMode(currentQuestion) : 'single'
  const progressPercent = session.questions.length > 0 ? Math.round((answeredCount / session.questions.length) * 100) : 0
  const examStats = [
    { label: '进度', value: `${answeredCount}/${session.questions.length}` },
    { label: '完成率', value: `${progressPercent}%` },
    { label: '当前题型', value: currentQuestion?.questionType || currentQuestion?.type || mode },
    { label: '本题分值', value: currentQuestion ? `${currentQuestion.maxScore} 分` : '-' },
  ]

  return (
    <div className="aurora-exam-screen flex h-screen flex-col">
      <header className="aurora-exam-topbar flex items-center justify-between gap-3 px-4 py-3">
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
          {session.mode === 'timed' && <ExamTimer remainingSeconds={remainingSeconds} />}
          <Button type="button" onClick={() => setConfirmOpen(true)}>
            <Send className="h-4 w-4" />
            交卷
          </Button>
        </div>
      </header>

      <div className="aurora-exam-canvas flex min-h-0 flex-1 flex-col md:flex-row">
        <QuestionNavigator
          questions={session.questions}
          currentIndex={currentQuestionIndex}
          answers={answers}
          onSelect={handleSelectQuestion}
        />

        <main className="flex min-w-0 flex-1 flex-col">
          {currentQuestion && (
            <div className="flex-1 overflow-auto p-5 md:p-8">
              <div className="mx-auto max-w-3xl space-y-6">
                <section className="aurora-exam-hero">
                  <div>
                    <div className="aurora-kicker">
                      <Sparkles className="h-3.5 w-3.5" />
                      Exam Cockpit
                    </div>
                    <h2 className="mt-3 text-2xl font-semibold tracking-tight">在线考试驾驶舱</h2>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      当前作答会自动保存，切题前同步手写内容，计时考试将在倒计时结束后自动交卷。
                    </p>
                  </div>
                  <div className="aurora-exam-stat-grid">
                    {examStats.map((item) => (
                      <div key={item.label} className="aurora-exam-stat">
                        <span>{item.label}</span>
                        <strong>{item.value}</strong>
                      </div>
                    ))}
                  </div>
                </section>

                <div className="aurora-exam-question-head flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium">第 {currentQuestionIndex + 1} 题</div>
                    <div className="text-xs text-muted-foreground">{currentQuestion.questionType || currentQuestion.type} · {currentQuestion.maxScore} 分</div>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {isSaving ? '保存中...' : lastSavedAt ? `已保存 ${lastSavedAt}` : '未保存'}
                  </div>
                </div>

                <section className="aurora-exam-card p-5" data-focus="true">
                  <QuestionContent content={currentQuestion.stem || ''} />
                </section>

                {mode === 'single' || mode === 'multi' ? (
                  <BubbleSheetCard
                    mode={mode}
                    options={extractOptions(currentQuestion.stem)}
                    value={answer?.selectedOptions || []}
                    onChange={(selectedOptions) =>
                      updateAnswer(currentQuestion.questionId, {
                        questionId: currentQuestion.questionId,
                        questionType: currentQuestion.questionType,
                        selectedOptions,
                      })
                    }
                  />
                ) : mode === 'fill' ? (
                  <Input
                    className="aurora-exam-input"
                    value={answer?.fillBlankText || ''}
                    onChange={(event) =>
                      updateAnswer(currentQuestion.questionId, {
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
                      key={currentQuestion.questionId}
                      ref={handwritingRef}
                      imageUrl={currentQuestion.studentAnswer?.handwritingImageUrl}
                      onImageFile={async (file) => {
                        const uploaded = await uploadHandwriting.mutateAsync({ questionId: currentQuestion.questionId, file })
                        updateAnswer(currentQuestion.questionId, {
                          questionId: currentQuestion.questionId,
                          questionType: currentQuestion.questionType,
                          handwritingImagePath: uploaded.path,
                        })
                      }}
                    />
                    <Textarea
                      value={answer?.textAnswer || ''}
                      onChange={(event) =>
                        updateAnswer(currentQuestion.questionId, {
                          questionId: currentQuestion.questionId,
                          questionType: currentQuestion.questionType,
                          textAnswer: event.target.value,
                        })
                      }
                      placeholder="可选文字补充"
                      className="aurora-exam-card min-h-24"
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          <footer className="aurora-exam-footer flex items-center justify-between p-3">
            <Button
              type="button"
              variant="outline"
              disabled={currentQuestionIndex <= 0}
              onClick={() => handleSelectQuestion(currentQuestionIndex - 1)}
            >
              <ChevronLeft className="h-4 w-4" />
              上一题
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={currentQuestionIndex >= session.questions.length - 1}
              onClick={() => handleSelectQuestion(currentQuestionIndex + 1)}
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
