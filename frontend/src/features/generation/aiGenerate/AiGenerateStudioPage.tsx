import { useEffect, useMemo, useState } from 'react'
import { FileText, History, Network, Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Sheet, SheetContent } from '@/components/ui/sheet'
import { useSubjectFilters, useSubjectKnowledgeTree, useSubjects } from '@/hooks/useSubjects'
import { ContextRail } from '@/features/generation/aiGenerate/ContextRail'
import { ConfirmedShelf } from '@/features/generation/aiGenerate/ConfirmedShelf'
import { MissionComposer } from '@/features/generation/aiGenerate/MissionComposer'
import { QuestionFloatingWindow } from '@/features/generation/aiGenerate/components/QuestionFloatingWindow'
import { MediaImportCard } from '@/features/generation/aiGenerate/components/MediaImportCard'
import { SessionHistoryPanel } from '@/features/generation/aiGenerate/components/SessionHistoryPanel'
import { StudioToolbar } from '@/features/generation/aiGenerate/components/StudioToolbar'
import { useDraftActions } from '@/features/generation/aiGenerate/hooks/useDraftActions'
import { useInfiniteMode } from '@/features/generation/aiGenerate/hooks/useInfiniteMode'
import { useSessionRestore } from '@/features/generation/aiGenerate/hooks/useSessionRestore'
import type { AiGenerateKnowledgeNode } from '@/features/generation/aiGenerate/types'
import { flattenKnowledgeNodes, statusLabel } from '@/features/generation/aiGenerate/studioUtils'
import { useQuestionLibrary } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'
import { useQuestionLibraryTasks } from '@/features/generation/questionLibrary/hooks/useQuestionLibraryTasks'
import { useNotificationStore } from '@/stores/useNotificationStore'

export function AiGenerateStudioPage() {
  const { data: subjects } = useSubjects()
  const pushToast = useNotificationStore((state) => state.pushToast)

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

  const sr = useSessionRestore({ currentSubject: lib.filters.subject, onSubjectChange: lib.setSubject, tasks, pushToast })
  const [historySheetOpen, setHistorySheetOpen] = useState(false)
  const [contextSheetOpen, setContextSheetOpen] = useState(false)
  const [questionWindowOpen, setQuestionWindowOpen] = useState(false)
  const [questionWindowDismissedKey, setQuestionWindowDismissedKey] = useState<string | null>(null)

  const { data: subjectFiltersData } = useSubjectFilters(lib.filters.subject || undefined)
  const subjectFilters = subjectFiltersData || {}

  const knowledgeTreeQuery = useSubjectKnowledgeTree(lib.filters.subject || undefined, {
    gradeId: sr.gradeId || undefined,
    textbookVersionId: sr.textbookVersionId || undefined,
  })
  const knowledgeTree = useMemo(() => ((knowledgeTreeQuery.data?.nodes || []) as AiGenerateKnowledgeNode[]), [knowledgeTreeQuery.data?.nodes])
  const knowledgeNodeMap = useMemo(() => flattenKnowledgeNodes(knowledgeTree), [knowledgeTree])

  const selectedKnowledgeNodeLabels = useMemo(() => {
    if (sr.selectedKnowledgePointLabels.length > 0) return sr.selectedKnowledgePointLabels
    return sr.selectedKnowledgePointIds.map((id) => knowledgeNodeMap[id]?.label || '').filter((item) => item.trim().length > 0)
  }, [knowledgeNodeMap, sr.selectedKnowledgePointIds, sr.selectedKnowledgePointLabels])

  useEffect(() => {
    if (lib.filters.subject) return
    const firstSubject = (subjects || []).find((item) => String(item.code || '').trim())
    if (firstSubject?.code) lib.setSubject(firstSubject.code)
  }, [lib, lib.filters.subject, subjects])

  const activeTask = tasks.preferredTask
  const currentTaskId = String(activeTask?.taskId || sr.session?.taskId || '').trim()
  const taskStatus = String(activeTask?.status || '').trim()
  const sessionStatus = String(sr.session?.status || '').trim()
  const isSessionRunning = sessionStatus === 'running'
  const effectiveTaskStatus = isSessionRunning ? 'running' : taskStatus || sessionStatus
  const isGenerating = effectiveTaskStatus === 'running'
  const currentTaskEvents = tasks.getTaskEvents(currentTaskId)
  const questionWindowKey = String(sr.activeSessionId || sr.session?.sessionId || 'current').trim()
  const questionWindowDismissed = questionWindowDismissedKey === questionWindowKey
  const questionWindowEffectiveOpen = questionWindowOpen && !questionWindowDismissed

  const inf = useInfiniteMode({
    subject: lib.filters.subject,
    pushToast,
    tasks,
    mode: sr.mode,
    setMode: sr.setMode,
    session: sr.session,
    setSession: sr.setSession,
    activeSessionId: sr.activeSessionId,
    setSearchParams: sr.setSearchParams,
    syncSessionFromServer: sr.syncSessionFromServer,
    optimisticStopRequestedRef: sr.optimisticStopRequestedRef,
    missionText: sr.missionText,
    difficulty: sr.difficulty,
    questionType: sr.questionType,
    count: sr.count,
    useStudyArchive: sr.useStudyArchive,
    useReferenceQuestions: sr.useReferenceQuestions,
    referenceSource: sr.referenceSource,
    referenceYearRange: sr.referenceYearRange,
    gradeId: sr.gradeId,
    textbookVersionId: sr.textbookVersionId,
    selectedKnowledgePointIds: sr.selectedKnowledgePointIds,
    selectedKnowledgeNodeLabels,
    intuitionPractice: sr.intuitionPractice,
    isGenerating,
  })

  const da = useDraftActions({
    session: sr.session,
    setSession: sr.setSession,
    setSearchParams: sr.setSearchParams,
    lib,
    tasks,
    pushToast,
    syncSessionFromServer: sr.syncSessionFromServer,
    onDisableAutoAppend: () => {
      inf.setAutoAppendEnabled(false)
    },
  })

  const committedDrafts = useMemo(() => {
    if (!sr.session) return []
    return sr.session.drafts.filter((draft) => draft.reviewStatus === 'committed')
  }, [sr.session])

  const draftCount = sr.session?.drafts.length || 0
  const statusChip = statusLabel(sr.session?.status || effectiveTaskStatus || '')

  const openQuestionWindow = () => {
    setQuestionWindowDismissedKey(null)
    setQuestionWindowOpen(true)
  }

  const closeQuestionWindow = () => {
    setQuestionWindowDismissedKey(questionWindowKey)
    setQuestionWindowOpen(false)
  }

  const runMediaImport = (payload: { files: File[]; maxQuestions: number }) => {
    if (!lib.filters.subject.trim() || payload.files.length === 0) return
    lib.setOrigin('media')
    setQuestionWindowDismissedKey(null)
    setQuestionWindowOpen(true)
    tasks.runMediaImport({
      subject: lib.filters.subject,
      topic: sr.missionText.trim(),
      difficulty: sr.difficulty,
      question_type: sr.questionType,
      count: payload.maxQuestions,
      max_pdf_pages: 12,
      files: payload.files,
    })
  }

  useEffect(() => {
    if (!questionWindowDismissed && (isGenerating || draftCount > 0)) {
      setQuestionWindowOpen(true)
    }
  }, [draftCount, isGenerating, questionWindowDismissed])

  const restoreSession = (sessionId: string) => {
    inf.setAutoAppendEnabled(false)
    setHistorySheetOpen(false)
    void sr.restoreSession(sessionId)
  }

  const handleToggleKnowledgePoint = (node: AiGenerateKnowledgeNode) => {
    sr.setSelectedKnowledgePointIds((prev) => {
      const exists = prev.includes(node.id)
      const nextIds = exists ? prev.filter((item) => item !== node.id) : [...prev, node.id]
      sr.setSelectedKnowledgePointLabels(
        nextIds.map((id) => knowledgeNodeMap[id]?.label || '').filter((item) => item.trim().length > 0)
      )
      return nextIds
    })
  }

  const clearKnowledgePoints = () => {
    sr.setSelectedKnowledgePointIds([])
    sr.setSelectedKnowledgePointLabels([])
  }

  return (
    <div className="h-full overflow-y-auto bg-[radial-gradient(circle_at_top,_rgba(50,106,255,0.10),_transparent_30%),linear-gradient(180deg,_rgba(248,245,238,0.95),_rgba(244,239,229,0.84))] text-foreground dark:bg-[radial-gradient(circle_at_top,_rgba(92,140,255,0.18),_transparent_40%),radial-gradient(circle_at_70%_0%,_rgba(255,210,140,0.10),_transparent_42%),linear-gradient(180deg,_rgba(14,16,24,1),_rgba(10,12,18,1))]">
      <div className="mx-auto flex min-h-full w-full max-w-[1440px] flex-col gap-6 px-4 py-6 lg:px-6 2xl:px-8">
        <section className="overflow-hidden rounded-[34px] border border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.97),rgba(248,243,233,0.92))] shadow-[0_26px_70px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(24,26,40,0.95),rgba(16,18,28,0.94))] dark:shadow-[0_28px_90px_rgba(0,0,0,0.56)]">
          <div className="flex flex-col gap-6 p-6 lg:p-8">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
              <div className="max-w-3xl">
                <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-sm font-medium text-primary">
                  <Sparkles className="h-4 w-4" />
                  AI 出题
                </div>
                <h1 className="mt-4 text-3xl font-semibold tracking-tight lg:text-4xl">像深度研究、AI 出卷一样先聚焦任务，再在悬浮窗里看题和审核</h1>
                <p className="mt-3 text-sm leading-7 text-muted-foreground lg:text-base">
                  主页面只保留任务描述、流程和关键配置；生成出的题目、答案、解析统一进入右侧悬浮窗，减少页面分散感。
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-3 lg:min-w-[440px]">
                <div className="rounded-[24px] border border-border/70 bg-background/80 p-4 shadow-sm">
                  <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">当前状态</div>
                  <div className="mt-2 flex items-center gap-2 text-sm font-medium">
                    <Badge variant="outline" className="rounded-full">
                      {statusChip || '待开始'}
                    </Badge>
                  </div>
                </div>
                <div className="rounded-[24px] border border-border/70 bg-background/80 p-4 shadow-sm">
                  <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">知识点</div>
                  <div className="mt-2 text-sm font-medium">已选 {selectedKnowledgeNodeLabels.length} 个</div>
                  <div className="mt-1 text-xs text-muted-foreground">可在知识点配置中调整</div>
                </div>
                <div className="rounded-[24px] border border-border/70 bg-background/80 p-4 shadow-sm">
                  <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">题目悬浮窗</div>
                  <div className="mt-2 text-sm font-medium">{draftCount > 0 ? `已生成 ${draftCount} 道题` : isGenerating ? '正在等待题目流入' : '尚未生成'}</div>
                  <div className="mt-1 text-xs text-muted-foreground">支持收起后再打开</div>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" variant="outline" className="rounded-full" onClick={() => setHistorySheetOpen(true)}>
                <History className="h-4 w-4" />
                会话历史
              </Button>
              <Button type="button" variant="outline" className="rounded-full" onClick={() => setContextSheetOpen(true)}>
                <Network className="h-4 w-4" />
                知识点配置
              </Button>
              <Button type="button" variant="outline" className="rounded-full" onClick={openQuestionWindow}>
                <FileText className="h-4 w-4" />
                打开题目悬浮窗
              </Button>
              {sr.session?.mission.subject ? (
                <Badge variant="outline" className="rounded-full">
                  {sr.session.mission.subject}
                </Badge>
              ) : null}
              <Badge variant="outline" className="rounded-full">
                {sr.mode === 'infinite' ? '无限模式' : '标准模式'}
              </Badge>
            </div>
          </div>
        </section>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-6">
            <MissionComposer
              missionText={sr.missionText}
              subject={lib.filters.subject}
              count={sr.count}
              difficulty={sr.difficulty}
              questionType={sr.questionType}
              useStudyArchive={sr.useStudyArchive}
              useReferenceQuestions={sr.useReferenceQuestions}
              referenceSource={sr.referenceSource}
              referenceYearRange={sr.referenceYearRange}
              practiceGoal={sr.intuitionPractice.practice_goal}
              intuitionKinds={sr.intuitionPractice.intuition_kinds}
              packetSize={sr.intuitionPractice.packet_size}
              feedbackMode={sr.intuitionPractice.feedback_mode}
              mode={sr.mode}
              subjects={(subjects || []).filter((item) => String((item as any).code || '').trim())}
              isGenerating={isGenerating}
              primaryActionLabel={inf.primaryActionLabel}
              canStop={Boolean(
                (sr.mode === 'infinite' || sr.session?.mode === 'infinite') &&
                  (inf.autoAppendEnabled || inf.isStopping || sr.session?.stopRequested || isGenerating)
              )}
              selectedKnowledgeCount={sr.selectedKnowledgePointIds.length}
              onMissionTextChange={sr.setMissionText}
              onSubjectChange={lib.setSubject}
              onCountChange={sr.setCount}
              onDifficultyChange={sr.setDifficulty}
              onQuestionTypeChange={sr.setQuestionType}
              onUseStudyArchiveChange={sr.setUseStudyArchive}
              onUseReferenceQuestionsChange={sr.setUseReferenceQuestions}
              onReferenceSourceChange={(value) => sr.setReferenceSource(value as 'any' | 'gaokao' | 'mock' | 'joint')}
              onReferenceYearRangeChange={(value) => sr.setReferenceYearRange(value as 'all' | '3' | '5')}
              onPracticeGoalChange={(value) => sr.setIntuitionPractice((prev) => ({ ...prev, practice_goal: value }))}
              onIntuitionKindsChange={(value) => sr.setIntuitionPractice((prev) => ({ ...prev, intuition_kinds: value }))}
              onPacketSizeChange={(value) => sr.setIntuitionPractice((prev) => ({ ...prev, packet_size: value }))}
              onFeedbackModeChange={(value) => sr.setIntuitionPractice((prev) => ({ ...prev, feedback_mode: value }))}
              onModeChange={sr.setMode}
              onGenerate={inf.startGeneration}
              onStop={inf.stopAppend}
            />

            <MediaImportCard
              subject={lib.filters.subject}
              topic={sr.missionText}
              difficulty={sr.difficulty}
              questionType={sr.questionType}
              isRunning={isGenerating}
              onRun={runMediaImport}
            />

            <StudioToolbar
              activeSessionId={sr.activeSessionId}
              currentTaskId={currentTaskId || sr.activeSessionId}
              session={sr.session}
              preferredTask={activeTask}
              taskEvents={currentTaskEvents}
              open={sr.workflowOpen}
              onOpenChange={sr.setWorkflowOpen}
            />

            <ConfirmedShelf drafts={committedDrafts} status={sr.session?.status} isDiscarding={da.isDiscarding} onDiscard={da.handleDiscard} />
          </div>

          <div className="space-y-4">
            <Card className="rounded-[28px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(247,241,231,0.92))] shadow-[0_18px_50px_rgba(29,33,44,0.07)] dark:bg-[linear-gradient(180deg,rgba(26,28,42,0.94),rgba(18,20,30,0.92))] dark:shadow-[0_18px_70px_rgba(0,0,0,0.55)]">
              <CardHeader className="pb-3">
                <CardTitle className="text-lg">当前出题摘要</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-muted-foreground">
                <div className="rounded-[20px] border border-border/70 bg-background/75 p-4">
                  <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">任务描述</div>
                  <div className="mt-2 line-clamp-5 leading-6 text-foreground">{sr.missionText || '请先输入出题任务描述。'}</div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                  <div className="rounded-[20px] border border-border/70 bg-background/75 p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">基础参数</div>
                    <div className="mt-2 leading-6 text-foreground">
                      {lib.filters.subject || '未选择学科'} · {sr.difficulty || '难度不限'} · {sr.count || '5'} 题
                    </div>
                  </div>
                  <div className="rounded-[20px] border border-border/70 bg-background/75 p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">参考范围</div>
                    <div className="mt-2 leading-6 text-foreground">
                      {sr.useStudyArchive ? '引用自学资料' : '不引用资料'}
                      <br />
                      {sr.useReferenceQuestions ? '参考真题' : '不参考真题'}
                    </div>
                  </div>
                  <div className="rounded-[20px] border border-border/70 bg-background/75 p-4">
                    <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">直觉练习</div>
                    <div className="mt-2 leading-6 text-foreground">
                      {sr.intuitionPractice.practice_goal === 'fluency'
                        ? '熟练感'
                        : sr.intuitionPractice.practice_goal === 'intuition_correction'
                          ? '直觉纠错'
                          : sr.intuitionPractice.practice_goal === 'transfer'
                            ? '迁移'
                            : sr.intuitionPractice.practice_goal === 'solution_appreciation'
                              ? '解法品鉴'
                              : '结构直觉'}
                      {' · '}每题 {sr.intuitionPractice.packet_size} 个直觉环节
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      <QuestionFloatingWindow
        key={`${questionWindowKey}:${questionWindowEffectiveOpen ? 'open' : 'closed'}`}
        open={questionWindowEffectiveOpen}
        session={sr.session}
        isGenerating={isGenerating}
        isFetching={sr.sessionDetailQuery.isFetching}
        draftRefs={da.draftRefs}
        onOpen={openQuestionWindow}
        onClose={closeQuestionWindow}
        onConfirm={da.handleConfirmDraft}
        onRegenerateSection={da.handleRegenerateSection}
        onSectionChange={da.handleSectionChange}
        onToggleSectionLock={da.handleToggleSectionLock}
      />

      <Sheet open={historySheetOpen} onOpenChange={setHistorySheetOpen}>
        <SheetContent side="left" className="w-[min(460px,100vw)] max-w-[460px] overflow-y-auto border-r border-border/70 bg-transparent p-0 shadow-none sm:max-w-[460px]">
          <div className="min-h-full p-4 sm:p-5">
            <SessionHistoryPanel
              open={sr.historyOpen}
              onOpenChange={sr.setHistoryOpen}
              isLoading={sr.sessionsQuery.isLoading}
              sessions={sr.historySessions}
              activeSessionId={sr.activeSessionId}
              onRestore={restoreSession}
              onArchive={sr.archiveSession}
            />
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={contextSheetOpen} onOpenChange={setContextSheetOpen}>
        <SheetContent side="right" className="w-[min(460px,100vw)] max-w-[460px] overflow-y-auto border-l border-border/70 bg-transparent p-0 shadow-none sm:max-w-[460px]">
          <div className="min-h-full p-4 sm:p-5">
            <ContextRail
              subject={lib.filters.subject}
              mode={sr.mode}
              sessionStatus={statusLabel(sr.session?.status || '')}
              gradeId={sr.gradeId}
              textbookVersionId={sr.textbookVersionId}
              grades={subjectFilters.grades || []}
              textbookVersions={subjectFilters.textbookVersions || []}
              knowledgeTree={knowledgeTree}
              isKnowledgeLoading={knowledgeTreeQuery.isFetching}
              knowledgeError={knowledgeTreeQuery.error instanceof Error ? knowledgeTreeQuery.error.message : undefined}
              selectedKnowledgeIds={sr.selectedKnowledgePointIds}
              selectedKnowledgeLabels={selectedKnowledgeNodeLabels}
              libraryTotal={lib.total}
              onGradeChange={sr.setGradeId}
              onTextbookVersionChange={sr.setTextbookVersionId}
              onToggleKnowledgePoint={handleToggleKnowledgePoint}
              onClearKnowledgePoints={clearKnowledgePoints}
            />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
