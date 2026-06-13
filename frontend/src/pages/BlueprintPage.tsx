import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useComposePaper, useSaveBlueprint } from '@/hooks/useBlueprint'
import { useSubjects, useSubjectFilters } from '@/hooks/useSubjects'
import { useAuthStore } from '@/stores/useAuthStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { generateId } from '@/lib/utils'
import { isRecord } from '@/lib/record'
import type { BlueprintSlot } from '@/types'
import { BlueprintPreviewPanel } from '@/features/generation/paperCompose/components/BlueprintPreviewPanel'
import type { QuestionTypeOption } from '@/features/generation/paperCompose/components/questionTypes'
import { useOneClickPaper } from '@/features/generation/paperCompose/hooks/useOneClickPaper'
import {
  useBlueprintDraft,
  useReuseTaskHydration,
  type BlueprintMode,
} from '@/features/generation/paperCompose/hooks/useBlueprintDraft'
import { extractSlotShortfalls } from '@/features/generation/paperCompose/utils/slotShortfalls'
import { BlueprintConfigPanel } from '@/features/generation/blueprint/components/BlueprintConfigPanel'

export default function BlueprintPage() {
  const userId = useAuthStore((s) => s.user?.id || '')
  const [searchParams, setSearchParams] = useSearchParams()
  const reuseTaskId = String(searchParams.get('reuse_task') || '').trim()

  const [mode, setMode] = useState<BlueprintMode>('blueprint')
  const [subject, setSubject] = useState('')
  const [topic, setTopic] = useState('')
  const [slots, setSlots] = useState<BlueprintSlot[]>([])
  const [blueprintName, setBlueprintName] = useState('')
  const [showQuestionTypes, setShowQuestionTypes] = useState(false)
  const [gradeId, setGradeId] = useState<string>('')
  const [textbookVersionId, setTextbookVersionId] = useState<string>('')

  const [oneClickTotalPoints, setOneClickTotalPoints] = useState<number>(150)
  const [oneClickTimeLimit, setOneClickTimeLimit] = useState<number>(120)
  const [oneClickHardPct, setOneClickHardPct] = useState<number>(20)
  const [oneClickUseArchive, setOneClickUseArchive] = useState<boolean>(true)

  const oneClick = useOneClickPaper()

  const { data: subjects } = useSubjects()
  const {
    data: filters,
    isLoading: isFiltersLoading,
    isFetching: isFiltersFetching,
    error: filtersError,
    refetch: refetchFilters,
  } = useSubjectFilters(subject || undefined)
  const { compose, pause, resume, isComposing, result, taskId, progress } = useComposePaper()
  const { mutate: saveBlueprint, isPending: isSaving } = useSaveBlueprint()

  const taskSteps = useTaskStore((state) => state.getTaskSteps(taskId ?? ''))
  const checkpoint = useTaskStore((state) => (taskId ? state.getCheckpoint(taskId) : undefined))

  const slotShortfalls = useMemo(() => extractSlotShortfalls(taskSteps || []), [taskSteps])

  const totalScore = slots.reduce(
    (sum, slot) => sum + slot.count * (slot.score || 0),
    0
  )
  const totalQuestions = slots.reduce((sum, slot) => sum + slot.count, 0)

  const handleAddSlot = (type: QuestionTypeOption) => {
    const newSlot: BlueprintSlot = {
      id: generateId(),
      questionType: type.name,
      count: 5,
      score: type.defaultScore,
      difficulty: 'medium',
    }
    setSlots([...slots, newSlot])
    setShowQuestionTypes(false)
  }

  const handleUpdateSlot = (index: number, slot: BlueprintSlot) => {
    const newSlots = [...slots]
    newSlots[index] = slot
    setSlots(newSlots)
  }

  const handleRemoveSlot = (index: number) => {
    setSlots(slots.filter((_, i) => i !== index))
  }

  const handleSubjectChange = useCallback((nextSubject: string) => {
    setSubject(nextSubject)
    setGradeId('')
    setTextbookVersionId('')
  }, [])

  const handleCompose = () => {
    if (!subject || slots.length === 0) return
    compose({
      subject,
      topic: topic.trim(),
      paperName: blueprintName.trim() || undefined,
      slots,
      filters: {
        gradeId: gradeId && gradeId !== 'all' ? Number(gradeId) : undefined,
        textbookVersion: textbookVersionId && textbookVersionId !== 'all' ? textbookVersionId : undefined,
      },
    })
  }

  const handleGenerateFull = useCallback(() => {
    oneClick.generate({
      subject,
      topic,
      paperName: blueprintName,
      totalPoints: oneClickTotalPoints,
      timeLimit: oneClickTimeLimit,
      hardPct: oneClickHardPct,
      useStudyArchive: oneClickUseArchive,
    })
  }, [
    blueprintName,
    oneClick,
    oneClickHardPct,
    oneClickTimeLimit,
    oneClickTotalPoints,
    oneClickUseArchive,
    subject,
    topic,
  ])

  const handleFillShortfalls = () => {
    if (!result || slotShortfalls.length === 0) return
    const ctxRaw = checkpoint?.checkpoint?.context
    const baseFromCheckpoint = isRecord(ctxRaw)
      ? (ctxRaw as unknown as Parameters<typeof compose>[0])
      : null

    compose({
      ...(baseFromCheckpoint ?? { subject, topic: topic.trim(), slots }),
      mode: 'fill_shortfalls',
      paperId: result.id,
      shortfalls: slotShortfalls,
    })
  }

  const handleSaveBlueprint = () => {
    if (!blueprintName || !subject || slots.length === 0) return
    saveBlueprint({ name: blueprintName, subject, topic: topic.trim(), slots })
    setBlueprintName('')
  }

  const isPaused = checkpoint?.status === 'paused'
  const progressPct = Number.isFinite(progress) ? progress : 0

  const draftSetters = useMemo(
    () => ({
      setMode,
      setSubject,
      setTopic,
      setSlots,
      setBlueprintName,
      setGradeId,
      setTextbookVersionId,
      setOneClickTotalPoints,
      setOneClickTimeLimit,
      setOneClickHardPct,
      setOneClickUseArchive,
    }),
    [],
  )

  useBlueprintDraft({
    userId,
    enabled: true,
    value: {
      mode,
      subject,
      topic,
      slots,
      blueprintName,
      gradeId,
      textbookVersionId,
      oneClickTotalPoints,
      oneClickTimeLimit,
      oneClickHardPct,
      oneClickUseArchive,
    },
    setters: draftSetters,
    hasResult: Boolean(result || oneClick.result),
  })

  useReuseTaskHydration({
    reuseTaskId,
    enabled: mode === 'blueprint',
    setters: draftSetters,
    onConsumed: () => {
      const next = new URLSearchParams(searchParams)
      next.delete('reuse_task')
      setSearchParams(next, { replace: true })
    },
  })

  return (
    <div className="aurora-blueprint-screen h-full grid grid-cols-12 overflow-hidden">
      {/* Left Panel: Configuration */}
      <BlueprintConfigPanel
        mode={mode}
        onModeChange={setMode}
        subjects={subjects}
        subject={subject}
        onSubjectChange={handleSubjectChange}
        topic={topic}
        onTopicChange={setTopic}
        filters={filters}
        isFiltersLoading={isFiltersLoading}
        isFiltersFetching={isFiltersFetching}
        filtersError={filtersError}
        onRefetchFilters={refetchFilters}
        gradeId={gradeId}
        onGradeChange={setGradeId}
        textbookVersionId={textbookVersionId}
        onTextbookVersionChange={setTextbookVersionId}
        slots={slots}
        totalQuestions={totalQuestions}
        totalScore={totalScore}
        showQuestionTypes={showQuestionTypes}
        onToggleQuestionTypes={() => setShowQuestionTypes(!showQuestionTypes)}
        onAddSlot={handleAddSlot}
        onUpdateSlot={handleUpdateSlot}
        onRemoveSlot={handleRemoveSlot}
        blueprintName={blueprintName}
        onBlueprintNameChange={setBlueprintName}
        isSaving={isSaving}
        onSaveBlueprint={handleSaveBlueprint}
        isComposing={isComposing}
        isPaused={isPaused}
        onPause={pause}
        onResume={resume}
        onCompose={handleCompose}
        oneClickTotalPoints={oneClickTotalPoints}
        onOneClickTotalPointsChange={setOneClickTotalPoints}
        oneClickTimeLimit={oneClickTimeLimit}
        onOneClickTimeLimitChange={setOneClickTimeLimit}
        oneClickHardPct={oneClickHardPct}
        onOneClickHardPctChange={setOneClickHardPct}
        oneClickUseArchive={oneClickUseArchive}
        onOneClickUseArchiveChange={setOneClickUseArchive}
        oneClick={oneClick}
        onGenerateFull={handleGenerateFull}
      />

      {/* Right Panel: Preview & Timeline */}
      <div className="aurora-blueprint-preview-shell col-span-5 h-full min-h-0">
        <BlueprintPreviewPanel
          mode={mode}
          isComposing={isComposing}
          taskId={taskId ?? undefined}
          progressPct={progressPct}
          result={result}
          taskSteps={taskSteps}
          slotShortfalls={slotShortfalls}
          onFillShortfalls={handleFillShortfalls}
          oneClick={oneClick}
        />
      </div>
    </div>
  )
}
