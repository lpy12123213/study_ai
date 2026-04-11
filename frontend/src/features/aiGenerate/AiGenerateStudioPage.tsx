import { useMemo } from 'react'
import { Separator } from '@/components/ui/separator'
import { useSubjectFilters, useSubjectKnowledgeTree, useSubjects } from '@/hooks/useSubjects'
import { useNotificationStore } from '@/stores/useNotificationStore'
import { ContextRail } from '@/features/aiGenerate/ContextRail'
import { ConfirmedShelf } from '@/features/aiGenerate/ConfirmedShelf'
import { DraftStream } from '@/features/aiGenerate/components/DraftStream'
import { SessionHistoryPanel } from '@/features/aiGenerate/components/SessionHistoryPanel'
import { StudioToolbar } from '@/features/aiGenerate/components/StudioToolbar'
import { useDraftActions } from '@/features/aiGenerate/hooks/useDraftActions'
import { useInfiniteMode } from '@/features/aiGenerate/hooks/useInfiniteMode'
import { useSessionRestore } from '@/features/aiGenerate/hooks/useSessionRestore'
import { MissionComposer } from '@/features/aiGenerate/MissionComposer'
import type { AiGenerateKnowledgeNode } from '@/features/aiGenerate/types'
import { flattenKnowledgeNodes, statusLabel } from '@/features/aiGenerate/studioUtils'
import { useQuestionLibrary } from '@/features/questionLibrary/hooks/useQuestionLibrary'
import { useQuestionLibraryTasks } from '@/features/questionLibrary/hooks/useQuestionLibraryTasks'

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

  const activeTask = tasks.preferredTask
  const currentTaskId = String(activeTask?.taskId || sr.session?.taskId || '').trim()
  const taskStatus = String(activeTask?.status || '').trim()
  const sessionStatus = String(sr.session?.status || '').trim()
  const isSessionRunning = sessionStatus === 'running'
  const effectiveTaskStatus = isSessionRunning ? 'running' : taskStatus || sessionStatus
  const isGenerating = effectiveTaskStatus === 'running'

  const currentTaskEvents = tasks.getTaskEvents(currentTaskId)

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

  const restoreSession = (sessionId: string) => {
    inf.setAutoAppendEnabled(false)
    void sr.restoreSession(sessionId)
  }

  const handleToggleKnowledgePoint = (node: AiGenerateKnowledgeNode) => {
    sr.setSelectedKnowledgePointIds((prev) => {
      const exists = prev.includes(node.id)
      return exists ? prev.filter((item) => item !== node.id) : [...prev, node.id]
    })
    sr.setSelectedKnowledgePointLabels((prev) => {
      const exists = prev.includes(node.label)
      return exists ? prev.filter((item) => item !== node.label) : [...prev, node.label]
    })
  }

  const clearKnowledgePoints = () => {
    sr.setSelectedKnowledgePointIds([])
    sr.setSelectedKnowledgePointLabels([])
  }

  return (
    <div className="h-full overflow-y-auto bg-[radial-gradient(circle_at_top,_rgba(50,106,255,0.12),_transparent_32%),linear-gradient(180deg,_rgba(248,245,238,0.94),_rgba(246,241,231,0.78))] text-foreground dark:bg-[radial-gradient(circle_at_top,_rgba(92,140,255,0.18),_transparent_40%),radial-gradient(circle_at_70%_0%,_rgba(255,210,140,0.10),_transparent_42%),linear-gradient(180deg,_rgba(14,16,24,1),_rgba(10,12,18,1))]">
      <div className="mx-auto flex min-h-full w-full max-w-[1920px] flex-col gap-6 px-4 py-6 lg:px-5 2xl:px-8">
        <div className="grid gap-5 xl:grid-cols-[260px_minmax(0,1fr)] 2xl:gap-6 2xl:grid-cols-[260px_minmax(0,1.55fr)_320px]">
          <SessionHistoryPanel open={sr.historyOpen} onOpenChange={sr.setHistoryOpen} isLoading={sr.sessionsQuery.isLoading} sessions={sr.historySessions} activeSessionId={sr.activeSessionId} onRestore={restoreSession} onArchive={sr.archiveSession} />

          <div className="flex min-w-0 flex-col gap-6">
            <StudioToolbar activeSessionId={sr.activeSessionId} currentTaskId={currentTaskId || sr.activeSessionId} session={sr.session} preferredTask={activeTask} taskEvents={currentTaskEvents} open={sr.workflowOpen} onOpenChange={sr.setWorkflowOpen} />

            <DraftStream session={sr.session} isGenerating={isGenerating} isFetching={sr.sessionDetailQuery.isFetching} draftRefs={da.draftRefs} onConfirm={da.handleConfirmDraft} onRegenerateSection={da.handleRegenerateSection} onSectionChange={da.handleSectionChange} onToggleSectionLock={da.handleToggleSectionLock} />

            <MissionComposer
              missionText={sr.missionText} subject={lib.filters.subject} count={sr.count} difficulty={sr.difficulty} questionType={sr.questionType}
              useStudyArchive={sr.useStudyArchive} useReferenceQuestions={sr.useReferenceQuestions} referenceSource={sr.referenceSource} referenceYearRange={sr.referenceYearRange} mode={sr.mode}
              subjects={(subjects || []).filter((item) => String((item as any).code || '').trim())}
              isGenerating={isGenerating} primaryActionLabel={inf.primaryActionLabel}
              canStop={Boolean(
                (sr.mode === 'infinite' || sr.session?.mode === 'infinite') &&
                  (inf.autoAppendEnabled || inf.isStopping || sr.session?.stopRequested || isGenerating)
              )}
              selectedKnowledgeCount={sr.selectedKnowledgePointIds.length}
              onMissionTextChange={sr.setMissionText} onSubjectChange={lib.setSubject} onCountChange={sr.setCount} onDifficultyChange={sr.setDifficulty} onQuestionTypeChange={sr.setQuestionType}
              onUseStudyArchiveChange={sr.setUseStudyArchive} onUseReferenceQuestionsChange={sr.setUseReferenceQuestions}
              onReferenceSourceChange={(value) => sr.setReferenceSource(value as 'any' | 'gaokao' | 'mock' | 'joint')}
              onReferenceYearRangeChange={(value) => sr.setReferenceYearRange(value as 'all' | '3' | '5')}
              onModeChange={sr.setMode} onGenerate={inf.startGeneration} onStop={inf.stopAppend}
            />
          </div>

          <div className="xl:col-span-2 2xl:col-auto">
            <ContextRail
              subject={lib.filters.subject} mode={sr.mode} sessionStatus={statusLabel(sr.session?.status || '')}
              gradeId={sr.gradeId} textbookVersionId={sr.textbookVersionId} grades={subjectFilters.grades || []} textbookVersions={subjectFilters.textbookVersions || []} knowledgeTree={knowledgeTree} isKnowledgeLoading={knowledgeTreeQuery.isFetching}
              knowledgeError={knowledgeTreeQuery.error instanceof Error ? knowledgeTreeQuery.error.message : undefined}
              selectedKnowledgeIds={sr.selectedKnowledgePointIds} selectedKnowledgeLabels={selectedKnowledgeNodeLabels} libraryTotal={lib.total}
              onGradeChange={sr.setGradeId} onTextbookVersionChange={sr.setTextbookVersionId} onToggleKnowledgePoint={handleToggleKnowledgePoint} onClearKnowledgePoints={clearKnowledgePoints}
            />
          </div>
        </div>

        <Separator className="opacity-60" />

        <ConfirmedShelf drafts={committedDrafts} status={sr.session?.status} isDiscarding={da.isDiscarding} onDiscard={da.handleDiscard} />
      </div>
    </div>
  )
}
