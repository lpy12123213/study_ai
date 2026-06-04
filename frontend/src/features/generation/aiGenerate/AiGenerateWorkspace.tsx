import { useMemo, useState } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useSubjects } from '@/hooks/useSubjects'
import { useQuestionLibrary } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'
import { useQuestionLibraryTasks } from '@/features/generation/questionLibrary/hooks/useQuestionLibraryTasks'
import { QuestionDetailDialog } from '@/features/generation/questionLibrary/QuestionDetailDialog'
import { QuestionBar } from '@/features/generation/questionLibrary/QuestionBar'
import { RunPanel } from '@/features/generation/questionLibrary/RunPanel'
import { GenerateConfigCard, DIFFICULTY_ANY } from '@/features/generation/aiGenerate/components/GenerateConfigCard'
import { DraftPreviewCard } from '@/features/generation/aiGenerate/components/DraftPreviewCard'
import { MediaImportCard } from '@/features/generation/aiGenerate/components/MediaImportCard'
import { RecentQuestionsSection } from '@/features/generation/aiGenerate/components/RecentQuestionsSection'
import { useAiGenerateDraftPreview } from '@/features/generation/aiGenerate/hooks/useAiGenerateDraftPreview'
import { useAiGenerateBulkSelection } from '@/features/generation/aiGenerate/hooks/useAiGenerateBulkSelection'

export function AiGenerateWorkspace() {
  const { data: subjects } = useSubjects()

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

  const [topic, setTopic] = useState('')
  const [difficulty, setDifficulty] = useState(DIFFICULTY_ANY)
  const [questionType, setQuestionType] = useState('')
  const [count, setCount] = useState('5')
  const [useStudyArchive, setUseStudyArchive] = useState(true)

  const [detailOpen, setDetailOpen] = useState(false)

  const preview = useAiGenerateDraftPreview({ lib, tasks })

  const bulk = useAiGenerateBulkSelection({
    lib,
    onCloseDetail: () => setDetailOpen(false),
  })

  const canGenerate = useMemo(() => {
    if (!lib.filters.subject.trim()) return false
    if (!topic.trim()) return false
    return true
  }, [lib.filters.subject, topic])

  const run = () => {
    if (!canGenerate) return

    const n = Number(count)
    const finalCount = Number.isFinite(n) ? Math.max(1, Math.min(10, Math.floor(n))) : 5

    tasks.runGenerate({
      subject: lib.filters.subject,
      topic: topic.trim(),
      difficulty: difficulty === DIFFICULTY_ANY ? '' : difficulty,
      question_type: questionType.trim(),
      count: finalCount,
      use_study_archive: Boolean(useStudyArchive),
    })
  }

  const runMediaImport = (payload: { files: File[]; maxQuestions: number }) => {
    if (!lib.filters.subject.trim() || !payload.files.length) return
    lib.setOrigin('media')
    tasks.runMediaImport({
      subject: lib.filters.subject,
      topic: topic.trim(),
      difficulty: difficulty === DIFFICULTY_ANY ? '' : difficulty,
      question_type: questionType.trim(),
      count: payload.maxQuestions,
      max_pdf_pages: 12,
      files: payload.files,
    })
  }

  const openDetail = (qid: string) => {
    lib.setSelectedId(qid)
    setDetailOpen(true)
  }

  const refreshAfterMutation = async () => {
    await lib.refreshList()
    await lib.refreshDetail()
  }

  return (
    <div className="h-full w-full flex flex-col overflow-hidden">
      <div className="px-6 py-4 border-b bg-background">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-lg font-semibold tracking-tight">AI 出题</div>
            <div className="text-xs text-muted-foreground">
              根据学科与知识点生成题目（含答案与解析）；生成后进入预览审核，通过后再入库。
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="p-6 space-y-6">
            <GenerateConfigCard
              subjects={subjects}
              subject={lib.filters.subject}
              onSubjectChange={lib.setSubject}
              topic={topic}
              onTopicChange={setTopic}
              difficulty={difficulty}
              onDifficultyChange={setDifficulty}
              questionType={questionType}
              onQuestionTypeChange={setQuestionType}
              count={count}
              onCountChange={setCount}
              useStudyArchive={useStudyArchive}
              onUseStudyArchiveChange={setUseStudyArchive}
              canGenerate={canGenerate}
              isRunning={tasks.preferredTask?.status === 'running'}
              onRun={run}
            />

            <MediaImportCard
              subject={lib.filters.subject}
              topic={topic}
              difficulty={difficulty === DIFFICULTY_ANY ? '' : difficulty}
              questionType={questionType}
              isRunning={tasks.preferredTask?.status === 'running'}
              onRun={runMediaImport}
            />

            {preview.draftPreview && preview.meta && (
              <DraftPreviewCard
                meta={preview.meta}
                draftQuestions={preview.draftQuestions}
                onChangeDraftQuestions={preview.setDraftQuestions}
                previewError={preview.previewError}
                isCommitting={preview.isCommitting}
                isDiscarding={preview.isDiscarding}
                onCommit={preview.commitPreview}
                onDiscard={preview.discardPreview}
              />
            )}

            <RecentQuestionsSection
              lib={lib}
              total={lib.total}
              bulkMode={bulk.bulkMode}
              onToggleBulkMode={bulk.toggleBulkMode}
              selectedCount={bulk.selectedCount}
              selectedIds={bulk.selectedIds}
              onSelectAllOnPage={bulk.selectAllOnPage}
              onClearSelection={bulk.clearSelection}
              onDeleteSelected={bulk.deleteSelected}
              isBulkDeleting={bulk.isBulkDeleting}
              bulkError={bulk.bulkError}
              onToggleSelected={bulk.toggleSelected}
              onOpenDetail={openDetail}
              onRefreshAfterMutation={refreshAfterMutation}
            />
          </div>
        </ScrollArea>
      </div>

      <QuestionBar />
      <RunPanel task={tasks.preferredTask} />

      <QuestionDetailDialog
        open={detailOpen}
        onOpenChange={(open) => {
          setDetailOpen(open)
          if (!open) lib.setSelectedId('')
        }}
        selectedId={lib.selectedId}
        listItem={lib.selectedItem}
        detail={lib.detail}
        isLoading={lib.detailQuery.isLoading}
        error={lib.detailQuery.error}
        onMutated={refreshAfterMutation}
      />
    </div>
  )
}
