import { useMemo, useState } from 'react'
import { BrainCircuit, Database, FileImage, Sparkles } from 'lucide-react'
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

  const engineStats = [
    { label: 'AI 题库', value: lib.total, icon: Database },
    { label: '草稿队列', value: preview.draftQuestions.length, icon: Sparkles },
    { label: '媒体录入', value: lib.filters.origin === 'media' ? 'Active' : 'Ready', icon: FileImage },
    { label: '运行态', value: tasks.preferredTask?.status === 'running' ? 'Running' : 'Idle', icon: BrainCircuit },
  ]

  return (
    <div className="aurora-ai-screen flex h-full w-full flex-col overflow-hidden">
      <div className="aurora-ai-header px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5 text-[var(--accent-brand-base)]" />
              Generation engine
            </div>
            <div className="app-display text-3xl text-foreground md:text-4xl">AI 出题引擎舱</div>
            <div className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              根据学科与知识点生成题目（含答案与解析）；生成后进入预览审核，通过后再入库。
            </div>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {engineStats.map((stat) => {
            const Icon = stat.icon
            return (
              <div key={stat.label} className="aurora-ai-stat p-4">
                <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                  <span>{stat.label}</span>
                  <Icon className="h-4 w-4 text-[var(--accent-brand-base)]" />
                </div>
                <div className="mt-2 font-mono text-2xl text-foreground">{stat.value}</div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="space-y-6 p-6">
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
