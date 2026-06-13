import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Sparkles } from 'lucide-react'
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
  const blueprintStats = [
    { label: '模式', value: mode === 'blueprint' ? '蓝图组卷' : '一键组卷' },
    { label: '题型槽', value: `${slots.length}` },
    { label: '题目数', value: `${totalQuestions}` },
    { label: '总分', value: `${totalScore}` },
  ]

  return (
    <div className="aurora-blueprint-config col-span-7 h-full overflow-auto p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <section className="aurora-blueprint-hero">
          <div>
            <div className="aurora-kicker">
              <Sparkles className="h-3.5 w-3.5" />
              Paper Blueprint Tower
            </div>
            <h1 className="mt-3 text-3xl font-bold tracking-tight">组卷蓝图控制塔</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              配置试卷结构、题型槽位、教材过滤和生成策略，AI 将自动搜索并组合题目。
            </p>
          </div>
          <div className="aurora-blueprint-stat-grid">
            {blueprintStats.map((item) => (
              <div key={item.label} className="aurora-blueprint-stat">
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
          <div className="mt-4">
            <Tabs value={mode} onValueChange={(v) => onModeChange(v as BlueprintMode)}>
              <TabsList className="aurora-blueprint-tabs">
                <TabsTrigger value="blueprint" onClick={() => onModeChange('blueprint')}>蓝图组卷</TabsTrigger>
                <TabsTrigger value="one_click" onClick={() => onModeChange('one_click')}>一键组卷</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </section>

        <div className="aurora-blueprint-section">
          <div className="aurora-blueprint-config-section">
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
          </div>
        </div>

        {mode === 'blueprint' ? (
          <>
            <div className="aurora-blueprint-section">
              <div className="aurora-blueprint-config-section">
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
              </div>
            </div>

            <div className="aurora-blueprint-section">
              <div className="aurora-blueprint-config-section">
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
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="aurora-blueprint-section">
              <div className="aurora-blueprint-config-section">
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
              </div>
            </div>

            <div className="aurora-blueprint-section">
              <div className="aurora-blueprint-config-section">
              <OneClickActionBar
                progress={oneClick.progress}
                taskId={oneClick.taskId}
                subject={subject}
                isGenerating={oneClick.isGenerating}
                onStop={oneClick.stop}
                onGenerate={onGenerateFull}
              />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
