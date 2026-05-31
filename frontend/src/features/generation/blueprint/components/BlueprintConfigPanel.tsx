import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { Subject } from '@/types'
import type { SubjectFilters } from '@/api/subjects'
import type { BlueprintSlot } from '@/types'
import { BlueprintBasicSettings } from '@/features/generation/paperCompose/components/BlueprintBasicSettings'
import { BlueprintSlotConfig } from '@/features/generation/paperCompose/components/BlueprintSlotConfig'
import { BlueprintActionBar } from '@/features/generation/paperCompose/components/BlueprintActionBar'
import { OneClickPaperForm } from '@/features/generation/paperCompose/components/OneClickPaperForm'
import { OneClickActionBar } from '@/features/generation/paperCompose/components/OneClickActionBar'
import type { QuestionTypeOption } from '@/features/generation/paperCompose/components/questionTypes'
import type { BlueprintMode } from '@/features/generation/paperCompose/hooks/useBlueprintDraft'
import type { useOneClickPaper } from '@/features/generation/paperCompose/hooks/useOneClickPaper'

export interface BlueprintConfigPanelProps {
  mode: BlueprintMode
  onModeChange: (mode: BlueprintMode) => void

  subjects: Subject[] | undefined
  subject: string
  onSubjectChange: (value: string) => void
  topic: string
  onTopicChange: (value: string) => void
  filters: SubjectFilters | undefined
  isFiltersLoading: boolean
  isFiltersFetching: boolean
  filtersError: unknown
  onRefetchFilters: () => void
  gradeId: string
  onGradeChange: (value: string) => void
  textbookVersionId: string
  onTextbookVersionChange: (value: string) => void

  slots: BlueprintSlot[]
  totalQuestions: number
  totalScore: number
  showQuestionTypes: boolean
  onToggleQuestionTypes: () => void
  onAddSlot: (type: QuestionTypeOption) => void
  onUpdateSlot: (index: number, slot: BlueprintSlot) => void
  onRemoveSlot: (index: number) => void

  blueprintName: string
  onBlueprintNameChange: (value: string) => void
  isSaving: boolean
  onSaveBlueprint: () => void
  isComposing: boolean
  isPaused: boolean
  onPause: () => void
  onResume: () => void
  onCompose: () => void

  oneClickTotalPoints: number
  onOneClickTotalPointsChange: (value: number) => void
  oneClickTimeLimit: number
  onOneClickTimeLimitChange: (value: number) => void
  oneClickHardPct: number
  onOneClickHardPctChange: (value: number) => void
  oneClickUseArchive: boolean
  onOneClickUseArchiveChange: (value: boolean) => void
  oneClick: ReturnType<typeof useOneClickPaper>
  onGenerateFull: () => void
}

export function BlueprintConfigPanel({
  mode,
  onModeChange,
  subjects,
  subject,
  onSubjectChange,
  topic,
  onTopicChange,
  filters,
  isFiltersLoading,
  isFiltersFetching,
  filtersError,
  onRefetchFilters,
  gradeId,
  onGradeChange,
  textbookVersionId,
  onTextbookVersionChange,
  slots,
  totalQuestions,
  totalScore,
  showQuestionTypes,
  onToggleQuestionTypes,
  onAddSlot,
  onUpdateSlot,
  onRemoveSlot,
  blueprintName,
  onBlueprintNameChange,
  isSaving,
  onSaveBlueprint,
  isComposing,
  isPaused,
  onPause,
  onResume,
  onCompose,
  oneClickTotalPoints,
  onOneClickTotalPointsChange,
  oneClickTimeLimit,
  onOneClickTimeLimitChange,
  oneClickHardPct,
  onOneClickHardPctChange,
  oneClickUseArchive,
  onOneClickUseArchiveChange,
  oneClick,
  onGenerateFull,
}: BlueprintConfigPanelProps) {
  return (
    <div className="col-span-7 h-full overflow-auto border-r border-border bg-background p-6">
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight mb-2">蓝图组卷</h1>
          <p className="text-muted-foreground">
            配置试卷结构，AI 将自动搜索并组合题目
          </p>
          <div className="mt-4">
            <Tabs value={mode} onValueChange={(v) => onModeChange(v as BlueprintMode)}>
              <TabsList>
                <TabsTrigger value="blueprint" onClick={() => onModeChange('blueprint')}>蓝图组卷</TabsTrigger>
                <TabsTrigger value="one_click" onClick={() => onModeChange('one_click')}>一键组卷</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </div>

        <BlueprintBasicSettings
          mode={mode}
          subjects={subjects}
          subject={subject}
          onSubjectChange={onSubjectChange}
          topic={topic}
          onTopicChange={onTopicChange}
          filters={filters}
          isFiltersLoading={isFiltersLoading}
          isFiltersFetching={isFiltersFetching}
          filtersError={filtersError}
          onRefetchFilters={onRefetchFilters}
          gradeId={gradeId}
          onGradeChange={onGradeChange}
          textbookVersionId={textbookVersionId}
          onTextbookVersionChange={onTextbookVersionChange}
        />

        {mode === 'blueprint' ? (
          <>
            <BlueprintSlotConfig
              slots={slots}
              totalQuestions={totalQuestions}
              totalScore={totalScore}
              showQuestionTypes={showQuestionTypes}
              onToggleQuestionTypes={onToggleQuestionTypes}
              onAddSlot={onAddSlot}
              onUpdateSlot={onUpdateSlot}
              onRemoveSlot={onRemoveSlot}
            />

            <BlueprintActionBar
              blueprintName={blueprintName}
              onBlueprintNameChange={onBlueprintNameChange}
              subject={subject}
              slotsCount={slots.length}
              isSaving={isSaving}
              onSaveBlueprint={onSaveBlueprint}
              isComposing={isComposing}
              isPaused={isPaused}
              onPause={onPause}
              onResume={onResume}
              onCompose={onCompose}
            />
          </>
        ) : (
          <>
            <OneClickPaperForm
              paperName={blueprintName}
              onPaperNameChange={onBlueprintNameChange}
              totalPoints={oneClickTotalPoints}
              onTotalPointsChange={onOneClickTotalPointsChange}
              timeLimit={oneClickTimeLimit}
              onTimeLimitChange={onOneClickTimeLimitChange}
              hardPct={oneClickHardPct}
              onHardPctChange={onOneClickHardPctChange}
              useArchive={oneClickUseArchive}
              onUseArchiveChange={onOneClickUseArchiveChange}
              error={oneClick.error}
            />

            <OneClickActionBar
              progress={oneClick.progress}
              taskId={oneClick.taskId}
              subject={subject}
              isGenerating={oneClick.isGenerating}
              onStop={oneClick.stop}
              onGenerate={onGenerateFull}
            />
          </>
        )}
      </div>
    </div>
  )
}
