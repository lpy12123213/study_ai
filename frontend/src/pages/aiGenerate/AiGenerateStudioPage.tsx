import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import {
  commitQuestionLibraryPreview,
  discardQuestionLibraryPreview,
  regenerateQuestionLibrarySection,
} from '@/api/questionLibrary'
import { useSubjects } from '@/hooks/useSubjects'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useToastStore } from '@/stores/useToastStore'
import { MissionComposer } from '@/pages/aiGenerate/MissionComposer'
import { GenerationStream } from '@/pages/aiGenerate/GenerationStream'
import { ContextRail } from '@/pages/aiGenerate/ContextRail'
import { ConfirmedShelf } from '@/pages/aiGenerate/ConfirmedShelf'
import { appendLatexConstraint } from '@/pages/aiGenerate/latexRules'
import { humanizeAiGenerateTaskError } from '@/pages/aiGenerate/humanizeTaskError'
import {
  applyRegeneratedDraftSection,
  createQueuedSession,
  failDraftSectionRegeneration,
  finalizeDraftSectionRegeneration,
  markDraftSectionRegenerating,
  reduceTaskPreviewToSession,
  toCommitQuestions,
  toggleDraftConfirmed,
  toggleDraftSectionLock,
  updateDraftSection,
} from '@/pages/aiGenerate/useAiGenerateSession'
import type { AiGenerateStudioSession, AiGenerateDraftCard } from '@/pages/aiGenerate/types'
import { useQuestionLibrary } from '@/pages/questionLibrary/hooks/useQuestionLibrary'
import { useQuestionLibraryTasks } from '@/pages/questionLibrary/hooks/useQuestionLibraryTasks'

const DEFAULT_MISSION =
  '为高一数学生成 5 道函数单调性中等难度题，包含答案和解析，并优先参考最近自学资料。'

function clampCount(raw: string): number {
  const value = Number(raw)
  if (!Number.isFinite(value)) return 5
  return Math.max(1, Math.min(10, Math.floor(value)))
}

function byQuestionId(session: AiGenerateStudioSession | null, ids: string[]): AiGenerateDraftCard[] {
  if (!session) return []
  const set = new Set(ids)
  return session.drafts.filter((draft) => set.has(draft.questionId))
}

export function AiGenerateStudioPage() {
  const { data: subjects } = useSubjects()
  const pushToast = useToastStore((state) => state.pushToast)

  const lib = useQuestionLibrary({
    initialFilters: {
      origin: 'ai',
      hidden: '0',
      sort: 'updated_at',
      order: 'desc',
    },
  })

  const tasks = useQuestionLibraryTasks({
    filters: lib.filters,
    restoreLatestPreview: true,
    onDone: async () => {
      await lib.refreshList()
      await lib.refreshDetail()
    },
  })

  const [missionText, setMissionText] = useState(DEFAULT_MISSION)
  const [difficulty, setDifficulty] = useState('中等')
  const [questionType, setQuestionType] = useState('')
  const [count, setCount] = useState('5')
  const [useStudyArchive, setUseStudyArchive] = useState(true)
  const [session, setSession] = useState<AiGenerateStudioSession | null>(null)
  const [isCommitting, setIsCommitting] = useState(false)
  const [isDiscarding, setIsDiscarding] = useState(false)

  const draftRefs = useRef<Array<HTMLDivElement | null>>([])
  const regenerateControllersRef = useRef<Record<string, AbortController>>({})

  useEffect(() => {
    if (!tasks.draftPreview) return
    setSession(reduceTaskPreviewToSession(tasks.draftPreview))
  }, [tasks.draftPreview])

  useEffect(() => {
    return () => {
      Object.values(regenerateControllersRef.current).forEach((controller) => controller.abort())
      regenerateControllersRef.current = {}
    }
  }, [])

  const subject = lib.filters.subject
  const activeTask = tasks.preferredTask
  const progress = Math.max(0, Math.min(100, Number(activeTask?.progress || 0)))
  const stage = String(activeTask?.stage || '').trim()
  const taskStatus = String(activeTask?.status || '').trim()
  const taskError = String(activeTask?.error || '').trim()
  const taskId = String(activeTask?.taskId || '').trim()
  const taskErrorInfo = useMemo(() => humanizeAiGenerateTaskError(taskError), [taskError])
  const draftCount = session?.drafts.length || 0
  const confirmedDrafts = useMemo(() => byQuestionId(session, session?.confirmedIds || []), [session])

  const lastFailedTaskToastRef = useRef('')

  useEffect(() => {
    if (taskStatus !== 'failed') return
    const message =
      (taskErrorInfo.code ? `${taskErrorInfo.display}（${taskErrorInfo.code}）` : taskErrorInfo.display) || '生成失败'
    const toastId = taskId ? `ai-generate-task-failed-${taskId}` : 'ai-generate-task-failed'
    const dedupeKey = `${toastId}:${message}`
    if (lastFailedTaskToastRef.current !== dedupeKey) {
      lastFailedTaskToastRef.current = dedupeKey
      pushToast({ id: toastId, title: message, status: 'failed' })
    }

    setSession((prev) => {
      if (!prev) return prev
      if (prev.previewId) return prev
      if (taskId && prev.taskId && prev.taskId !== taskId) return prev
      // Clear the queued placeholders so the UI doesn't look "stuck streaming" after failure.
      return null
    })
  }, [pushToast, taskErrorInfo.code, taskErrorInfo.display, taskId, taskStatus])

  const startGeneration = () => {
    const nextCount = clampCount(count)
    const rawMission = missionText.trim()
    if (!subject.trim() || !rawMission) {
      pushToast({ id: 'ai-generate-missing-input', title: '请先填写学科和任务描述', status: 'failed' })
      return
    }
    const topic = appendLatexConstraint(rawMission)

    const taskId = tasks.runGenerate({
      subject,
      topic,
      difficulty: difficulty.trim(),
      question_type: questionType.trim(),
      count: nextCount,
      use_study_archive: useStudyArchive,
    })

    setSession(
      createQueuedSession({
        taskId,
        subject,
        topic,
        count: nextCount,
      })
    )
  }

  const handleSectionChange = (questionId: string, sectionKey: keyof AiGenerateDraftCard['sections'], content: string) => {
    setSession((prev) => (prev ? updateDraftSection(prev, questionId, sectionKey, content) : prev))
  }

  const handleToggleSectionLock = (questionId: string, sectionKey: keyof AiGenerateDraftCard['sections']) => {
    setSession((prev) => (prev ? toggleDraftSectionLock(prev, questionId, sectionKey) : prev))
  }

  const handleRegenerateSection = (questionId: string, sectionKey: keyof AiGenerateDraftCard['sections']) => {
    const activeSession = session
    if (!activeSession?.previewId) {
      pushToast({ id: 'ai-generate-regenerate-missing-preview', title: '请等待草稿生成完成后再重生成片段', status: 'failed' })
      return
    }

    const targetDraft = activeSession.drafts.find((draft) => draft.questionId === questionId)
    if (!targetDraft) return
    if (targetDraft.sections[sectionKey].locked) {
      pushToast({ id: `ai-generate-locked-${questionId}-${sectionKey}`, title: '该片段已锁定，请先解锁后再重生成', status: 'failed' })
      return
    }

    const requestKey = `${questionId}:${sectionKey}`
    regenerateControllersRef.current[requestKey]?.abort()
    const controller = new AbortController()
    regenerateControllersRef.current[requestKey] = controller

    setSession((prev) => (prev ? markDraftSectionRegenerating(prev, questionId, sectionKey) : prev))
    pushToast({
      id: `ai-generate-rerender-${questionId}-${sectionKey}`,
      title: `已重新排队 ${sectionKey === 'stem' ? '题干' : sectionKey === 'answer' ? '答案' : '解析'} 片段`,
      status: 'running',
    })

    regenerateQuestionLibrarySection(
      activeSession.previewId,
      {
        question_id: questionId,
        section_key: sectionKey,
      },
      (event) => {
        if (event.type === 'done') {
          const data = event.data || {}
          const content = String(data.content || '').trim()
          setSession((prev) => (prev ? applyRegeneratedDraftSection(prev, questionId, sectionKey, content) : prev))
          pushToast({
            id: `ai-generate-regenerate-done-${questionId}-${sectionKey}`,
            title: `${sectionKey === 'stem' ? '题干' : sectionKey === 'answer' ? '答案' : '解析'} 已更新`,
            status: 'completed',
          })
          return
        }

        if (event.type === 'error') {
          setSession((prev) => (prev ? failDraftSectionRegeneration(prev, questionId, sectionKey) : prev))
          const message = String(event.data?.message || '片段重生成失败').trim() || '片段重生成失败'
          pushToast({
            id: `ai-generate-regenerate-error-${questionId}-${sectionKey}`,
            title: message,
            status: 'failed',
          })
        }
      },
      (error) => {
        setSession((prev) => (prev ? failDraftSectionRegeneration(prev, questionId, sectionKey) : prev))
        pushToast({
          id: `ai-generate-regenerate-network-${questionId}-${sectionKey}`,
          title: error.message || '片段重生成失败',
          status: 'failed',
        })
      },
      () => {
        delete regenerateControllersRef.current[requestKey]
        setSession((prev) => {
          if (!prev) return prev
          const target = prev.drafts.find((draft) => draft.questionId === questionId)
          if (!target) return prev
          if (target.sections[sectionKey].status === 'streaming') {
            return finalizeDraftSectionRegeneration(prev, questionId, sectionKey)
          }
          return prev
        })
      },
      { signal: controller.signal }
    )
  }

  const handleConfirmDraft = (questionId: string) => {
    setSession((prev) => (prev ? toggleDraftConfirmed(prev, questionId) : prev))
  }

  const handleCommit = async () => {
    if (!session?.previewId) {
      pushToast({ id: 'ai-generate-commit-missing-preview', title: '请等待草稿生成完成后再入库', status: 'failed' })
      return
    }
    if (confirmedDrafts.length === 0) {
      pushToast({ id: 'ai-generate-empty-confirmed', title: '请至少确认 1 道题再入库', status: 'failed' })
      return
    }

    setIsCommitting(true)
    try {
      const result = await commitQuestionLibraryPreview(session.previewId, toCommitQuestions(session))
      pushToast({
        id: `ai-generate-commit-${session.previewId}`,
        title: `已入库 ${Number(result.inserted || 0)} 道题`,
        status: 'completed',
      })
      tasks.clearDraftPreview()
      setSession(null)
      await lib.refreshList()
    } catch (error: any) {
      pushToast({
        id: `ai-generate-commit-failed-${session.previewId}`,
        title: error?.message || '入库失败',
        status: 'failed',
      })
    } finally {
      setIsCommitting(false)
    }
  }

  const handleDiscard = async () => {
    if (!session?.previewId) {
      setSession(null)
      return
    }
    setIsDiscarding(true)
    try {
      await discardQuestionLibraryPreview(session.previewId)
      tasks.clearDraftPreview()
      setSession(null)
      pushToast({ id: `ai-generate-discard-${session.previewId}`, title: '草稿已丢弃', status: 'completed' })
    } catch (error: any) {
      pushToast({
        id: `ai-generate-discard-failed-${session.previewId}`,
        title: error?.message || '丢弃失败',
        status: 'failed',
      })
    } finally {
      setIsDiscarding(false)
    }
  }

  const scrollToDraft = (index: number) => {
    const node = draftRefs.current[index]
    if (!node) return
    node.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="h-full overflow-y-auto bg-[radial-gradient(circle_at_top,_rgba(50,106,255,0.12),_transparent_32%),linear-gradient(180deg,_rgba(248,245,238,0.94),_rgba(246,241,231,0.78))] text-foreground dark:bg-[radial-gradient(circle_at_top,_rgba(92,140,255,0.18),_transparent_40%),radial-gradient(circle_at_70%_0%,_rgba(255,210,140,0.10),_transparent_42%),linear-gradient(180deg,_rgba(14,16,24,1),_rgba(10,12,18,1))]">
      <div className="mx-auto flex min-h-full w-full max-w-[1600px] flex-col gap-6 px-6 py-6 lg:px-8">
        <MissionComposer
          missionText={missionText}
          subject={subject}
          count={count}
          difficulty={difficulty}
          questionType={questionType}
          useStudyArchive={useStudyArchive}
          subjects={(subjects || []).filter((item) => String(item.code || '').trim())}
          isGenerating={taskStatus === 'running'}
          onMissionTextChange={setMissionText}
          onSubjectChange={lib.setSubject}
          onCountChange={setCount}
          onDifficultyChange={setDifficulty}
          onQuestionTypeChange={setQuestionType}
          onUseStudyArchiveChange={setUseStudyArchive}
          onGenerate={startGeneration}
        />

        <section className="grid min-h-[560px] gap-6 xl:grid-cols-[minmax(0,1.6fr)_340px]">
          <Card className="rounded-[32px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.94),rgba(251,248,241,0.9))] shadow-[0_22px_60px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(26,28,42,0.94),rgba(18,20,30,0.92))] dark:shadow-[0_22px_70px_rgba(0,0,0,0.55)]">
            <CardHeader className="border-b border-border/60 pb-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-lg">Generation Stream</CardTitle>
                  <div className="text-sm text-muted-foreground">
                    题目会按题干、答案、解析的顺序逐步出现，公式会即时按 LaTeX 渲染。
                  </div>
                </div>
                {taskStatus === 'running' && (
                  <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 dark:border-sky-800/70 dark:bg-sky-950/45 dark:text-sky-200">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    生成中
                  </div>
                )}
              </div>
            </CardHeader>
            <CardContent className="h-[640px] p-4 lg:p-6">
              {taskStatus === 'failed' && taskErrorInfo.display ? (
                <div className="mb-4 rounded-[24px] border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                  <div>{taskErrorInfo.display}</div>
                  {taskErrorInfo.code ? (
                    <code className="mt-2 block w-fit rounded-full border border-destructive/20 bg-destructive/10 px-3 py-1 font-mono text-xs text-destructive/90">
                      {taskErrorInfo.code}
                    </code>
                  ) : null}
                </div>
              ) : null}
              {session ? (
                <GenerationStream
                  drafts={session.drafts}
                  getDraftRef={(index) => (node) => {
                    draftRefs.current[index] = node
                  }}
                  onConfirm={handleConfirmDraft}
                  onRegenerateSection={handleRegenerateSection}
                  onSectionChange={handleSectionChange}
                  onToggleSectionLock={handleToggleSectionLock}
                />
              ) : (
                <div className="flex h-full items-center justify-center rounded-[28px] border border-dashed border-border bg-background/60 px-6 text-center">
                  <div className="max-w-lg space-y-3">
                    <div className="text-xl font-semibold">从一句任务开始</div>
                    <div className="text-sm leading-6 text-muted-foreground">
                      在顶部描述出题目标后，系统会先建立一个生成会话，再按题干、答案、解析逐题展开。数学公式会强制使用 LaTeX 并即时渲染。
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <ContextRail
            missionText={missionText}
            subject={subject}
            difficulty={difficulty}
            count={count}
            questionType={questionType}
            useStudyArchive={useStudyArchive}
            progress={progress}
            stage={stage}
            taskStatus={taskStatus}
            taskError={taskError}
            draftCount={draftCount}
            confirmedCount={confirmedDrafts.length}
            libraryTotal={lib.total}
            onScrollToDraft={scrollToDraft}
          />
        </section>

        <ConfirmedShelf
          drafts={confirmedDrafts}
          isCommitting={isCommitting}
          isDiscarding={isDiscarding}
          onRemove={handleConfirmDraft}
          onCommit={handleCommit}
          onDiscard={handleDiscard}
        />
      </div>
    </div>
  )
}
