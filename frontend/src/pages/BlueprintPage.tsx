import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  Trash2,
  Play,
  Pause,
  FileText,
  Loader2,
  ChevronDown,
  Save,
  Settings2,
  Layers,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  Square,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Progress } from '@/components/ui/progress'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { TaskProgressHeader } from '@/components/task/TaskProgressHeader'
import { useComposePaper, useSaveBlueprint } from '@/hooks/useBlueprint'
import { useSubjects, useSubjectFilters } from '@/hooks/useSubjects'
import { useFormDraft } from '@/hooks/useFormDraft'
import { useAuthStore } from '@/stores/useAuthStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn, generateId } from '@/lib/utils'
import { generateFullPaperStream, type GenerateFullPaperStreamEvent } from '@/api/papers'
import type { BlueprintSlot, TaskStep } from '@/types'
import * as tasksApi from '@/api/tasks'

type SlotShortfall = {
  slotIndex: number
  questionType: string
  difficulty: string
  requested: number
  selected: number
}

const defaultQuestionTypes = [
  { id: 'single_choice', name: '单选题', defaultScore: 3 },
  { id: 'multi_choice', name: '多选题', defaultScore: 4 },
  { id: 'fill_blank', name: '填空题', defaultScore: 4 },
  { id: 'short_answer', name: '简答题', defaultScore: 8 },
  { id: 'calculation', name: '计算题', defaultScore: 10 },
  { id: 'essay', name: '论述题', defaultScore: 12 },
]

interface SlotEditorProps {
  slot: BlueprintSlot
  onUpdate: (slot: BlueprintSlot) => void
  onRemove: () => void
}

function SlotEditor({ slot, onUpdate, onRemove }: SlotEditorProps) {
  return (
    <div className="grid grid-cols-12 gap-3 items-center py-3 border-b border-border/50 last:border-0 text-sm hover:bg-muted/30 transition-colors px-2 rounded-md">
      <div className="col-span-3 font-medium">{slot.questionType}</div>
      <div className="col-span-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-8">数量</span>
          <Input
            type="number"
            min={1}
            max={50}
            value={slot.count}
            onChange={(e) => onUpdate({ ...slot, count: parseInt(e.target.value) || 1 })}
            className="h-8"
          />
        </div>
      </div>
      <div className="col-span-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-8">分值</span>
          <Input
            type="number"
            min={1}
            max={100}
            value={slot.score || 0}
            onChange={(e) => onUpdate({ ...slot, score: parseInt(e.target.value) || 0 })}
            className="h-8"
          />
        </div>
      </div>
      <div className="col-span-2">
        <Select
          value={slot.difficulty || 'medium'}
          onValueChange={(value) => onUpdate({ ...slot, difficulty: value })}
        >
          <SelectTrigger className="h-8 w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="easy">简单</SelectItem>
            <SelectItem value="medium">中等</SelectItem>
            <SelectItem value="hard">困难</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="col-span-1 text-right">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

export default function BlueprintPage() {
  const userId = useAuthStore((s) => s.user?.id || '')
  const [searchParams, setSearchParams] = useSearchParams()
  const reuseTaskId = String(searchParams.get('reuse_task') || '').trim()

  const [mode, setMode] = useState<'blueprint' | 'one_click'>('blueprint')
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
  const [oneClickProgress, setOneClickProgress] = useState<number>(0)
  const [oneClickSteps, setOneClickSteps] = useState<TaskStep[]>([])
  const [oneClickTaskId, setOneClickTaskId] = useState<string>('')
  const [oneClickError, setOneClickError] = useState<string>('')
  const [oneClickResult, setOneClickResult] = useState<{
    paperId: number
    paperName: string
    questionCount: number
  } | null>(null)
  const [isGeneratingFull, setIsGeneratingFull] = useState<boolean>(false)
  const oneClickAbortRef = useRef<AbortController | null>(null)

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
  const checkpoint = useTaskStore((state) =>
    taskId ? state.getCheckpoint(taskId) : undefined
  )

  const slotShortfalls = useMemo<SlotShortfall[]>(() => {
    const step = (taskSteps || []).find((s) => s?.id === 'paper_balance')
    const out = (step as any)?.output
    const list: unknown[] = Array.isArray(out?.slotShortfalls) ? out.slotShortfalls : []
    return (list as any[])
      .filter((x: any) => x && typeof x === 'object')
      .map((x: any): SlotShortfall => ({
        slotIndex: Number(x.slotIndex),
        questionType: typeof x.questionType === 'string' ? x.questionType : '',
        difficulty: typeof x.difficulty === 'string' ? x.difficulty : '',
        requested: Number(x.requested || 0),
        selected: Number(x.selected || 0),
      }))
      .filter((x: SlotShortfall) => Number.isFinite(x.slotIndex) && x.requested > x.selected)
  }, [taskSteps])

  const totalScore = slots.reduce(
    (sum, slot) => sum + slot.count * (slot.score || 0),
    0
  )
  const totalQuestions = slots.reduce((sum, slot) => sum + slot.count, 0)

  const upsertOneClickStep = useCallback((incoming: TaskStep) => {
    setOneClickSteps((prev) => {
      const idx = prev.findIndex((s) => s.id === incoming.id)
      if (idx >= 0) {
        const next = [...prev]
        next[idx] = { ...next[idx], ...incoming }
        return next
      }
      return [...prev, incoming]
    })
  }, [])

  const handleAddSlot = (type: { id: string; name: string; defaultScore: number }) => {
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
    if (!subject) return

    oneClickAbortRef.current?.abort()
    const controller = new AbortController()
    oneClickAbortRef.current = controller

    const taskId = generateId().slice(0, 12)
    setOneClickTaskId(taskId)
    setOneClickError('')
    setOneClickResult(null)
    setOneClickSteps([])
    setOneClickProgress(0)
    setIsGeneratingFull(true)

    const hard = Math.max(0, Math.min(0.6, Number(oneClickHardPct || 0) / 100))
    const easy = (1 - hard) * 0.4
    const medium = Math.max(0, 1 - hard - easy)
    const difficultyDistribution = {
      easy: Number(easy.toFixed(2)),
      medium: Number(medium.toFixed(2)),
      hard: Number(hard.toFixed(2)),
    }

    const safeTotalPoints = Math.max(30, Math.min(Number(oneClickTotalPoints || 150), 300))
    const safeTimeLimit = Math.max(30, Math.min(Number(oneClickTimeLimit || 120), 240))

    generateFullPaperStream(
      {
        taskId,
        subject,
        topic: topic.trim() || undefined,
        paperName: blueprintName.trim() || undefined,
        totalPoints: safeTotalPoints,
        timeLimit: safeTimeLimit,
        difficultyDistribution,
        useStudyArchive: Boolean(oneClickUseArchive),
      },
      (evt: GenerateFullPaperStreamEvent) => {
        const kind = String(evt?.type || '').trim()
        if (kind === 'progress') {
          const p = Number((evt as any).progress)
          if (Number.isFinite(p)) setOneClickProgress(p)
          return
        }

        if (kind === 'step' && evt?.step && typeof evt.step === 'object') {
          const step = evt.step as any
          if (typeof step.id === 'string' && typeof step.title === 'string' && typeof step.status === 'string') {
            upsertOneClickStep(step as TaskStep)
          }
          return
        }

        if (kind === 'result' && evt?.result && typeof evt.result === 'object') {
          const result = evt.result as any
          const paperId = Number(result.paper_id)
          if (Number.isFinite(paperId)) {
            setOneClickResult({
              paperId,
              paperName: typeof result.paper_name === 'string' ? result.paper_name : `试卷-${paperId}`,
              questionCount: Number(result.question_count || 0),
            })
          }
          setOneClickProgress(100)
          setIsGeneratingFull(false)
          return
        }

        if (kind === 'error') {
          const message =
            typeof (evt as any).error === 'string'
              ? (evt as any).error
              : typeof (evt as any).message === 'string'
                ? (evt as any).message
                : 'generate_full_failed'
          setOneClickError(message)
          setIsGeneratingFull(false)
        }
      },
      (error) => {
        setOneClickError(error?.message || 'generate_full_failed')
        setIsGeneratingFull(false)
      },
      () => {
        setIsGeneratingFull(false)
      },
      { signal: controller.signal }
    )
  }, [
    blueprintName,
    oneClickHardPct,
    oneClickTimeLimit,
    oneClickTotalPoints,
    oneClickUseArchive,
    subject,
    topic,
    upsertOneClickStep,
  ])

  const handleStopGenerateFull = useCallback(() => {
    oneClickAbortRef.current?.abort()
    oneClickAbortRef.current = null
    setIsGeneratingFull(false)
  }, [])

  const handleFillShortfalls = () => {
    if (!result || slotShortfalls.length === 0) return
    const ctx = (checkpoint as any)?.checkpoint?.context
    const base = ctx && typeof ctx === 'object' ? ctx : { subject, topic: topic.trim(), slots }

    compose({
      ...(base as any),
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

  const draftKey = `draft:blueprint:v1:${userId || 'anon'}`
  const { clearDraft } = useFormDraft({
    storageKey: draftKey,
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
    shouldSave: (v) => {
      const anySlot = Array.isArray((v as any)?.slots) && (v as any).slots.length > 0
      return Boolean(String((v as any)?.subject || '').trim() || String((v as any)?.topic || '').trim() || anySlot)
    },
    onRestore: (data: any) => {
      setMode(data?.mode === 'one_click' ? 'one_click' : 'blueprint')
      setSubject(String(data?.subject || ''))
      setTopic(String(data?.topic || ''))
      setBlueprintName(String(data?.blueprintName || ''))
      setGradeId(String(data?.gradeId || ''))
      setTextbookVersionId(String(data?.textbookVersionId || ''))
      setOneClickTotalPoints(Number(data?.oneClickTotalPoints || 150))
      setOneClickTimeLimit(Number(data?.oneClickTimeLimit || 120))
      setOneClickHardPct(Number(data?.oneClickHardPct || 20))
      setOneClickUseArchive(Boolean(data?.oneClickUseArchive ?? true))
      const restoredSlots = Array.isArray(data?.slots) ? data.slots : []
      setSlots(
        restoredSlots
          .filter((s: any) => s && typeof s === 'object')
          .map((s: any) => ({
            id: String(s.id || generateId()),
            questionType: String(s.questionType || ''),
            count: Number(s.count || 1),
            score: Number(s.score || 0),
            difficulty: String(s.difficulty || 'medium'),
          })),
      )
    },
  })

  useEffect(() => {
    if (!result && !oneClickResult) return
    clearDraft()
  }, [clearDraft, oneClickResult, result])

  useEffect(() => {
    return () => {
      oneClickAbortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (!reuseTaskId) return
    if (mode !== 'blueprint') return
    let active = true
    const run = async () => {
      try {
        const task = await tasksApi.getTask(reuseTaskId)
        if (!active) return
        const req = (task as any)?.request
        if (!req || typeof req !== 'object') return
        const subject = String((req as any).subject || '')
        const topic = String((req as any).topic || '')
        const paperName = String((req as any).paperName || (req as any).paper_name || '')
        const slots = Array.isArray((req as any).slots) ? (req as any).slots : []
        const filters = (req as any).filters && typeof (req as any).filters === 'object' ? (req as any).filters : {}

        setSubject(subject)
        setTopic(topic)
        setBlueprintName(paperName)
        setGradeId(filters.gradeId != null ? String(filters.gradeId) : '')
        setTextbookVersionId(filters.textbookVersion != null ? String(filters.textbookVersion) : '')
        setSlots(
          slots
            .filter((s: any) => s && typeof s === 'object')
            .map((s: any) => ({
              id: generateId(),
              questionType: String(s.questionType || s.question_type || ''),
              count: Number(s.count || 1),
              score: Number(s.score || 0),
              difficulty: String(s.difficulty || 'medium'),
            })),
        )
      } finally {
        const next = new URLSearchParams(searchParams)
        next.delete('reuse_task')
        setSearchParams(next, { replace: true })
      }
    }
    void run()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, reuseTaskId])

  return (
    <div className="h-full grid grid-cols-12 overflow-hidden">
      {/* Left Panel: Configuration */}
      <div className="col-span-7 h-full overflow-auto border-r border-border bg-background p-6">
        <div className="max-w-3xl mx-auto space-y-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight mb-2">蓝图组卷</h1>
            <p className="text-muted-foreground">
              配置试卷结构，AI 将自动搜索并组合题目
            </p>
            <div className="mt-4">
              <Tabs value={mode} onValueChange={(v) => setMode(v as any)}>
                <TabsList>
                  <TabsTrigger value="blueprint">蓝图组卷</TabsTrigger>
                  <TabsTrigger value="one_click">一键组卷</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>

          <Card className="surface-raised">
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Settings2 className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">基本设置</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium mb-1.5 block">学科</label>
                <Select
                  value={subject}
                  onValueChange={setSubject}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="选择学科" />
                  </SelectTrigger>
                  <SelectContent>
                    {(subjects || [])
                      .filter((s) => (s.code || '').trim().length > 0)
                      .map((s) => (
                        <SelectItem key={s.id} value={s.code}>
                          {s.name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <label className="text-sm font-medium mb-1.5 block">考查主题</label>
                <Input
                  placeholder="如：导数 / 函数 / 圆锥曲线 / 阅读理解"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                />
              </div>

              {mode === 'blueprint' && !!subject && isFiltersLoading && (
                <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  正在初始化筛选项，首次加载该学科可能需要几秒。
                </div>
              )}

              {mode === 'blueprint' && !!subject && !!filtersError && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300">
                    <AlertTriangle className="h-4 w-4" />
                    筛选项加载失败，可重试后继续组卷。
                  </div>
                  <Button type="button" variant="outline" size="sm" onClick={() => refetchFilters()}>
                    重试
                  </Button>
                </div>
              )}

              {mode === 'blueprint' && !!subject && !isFiltersLoading && !filtersError && isFiltersFetching && (
                <div className="text-xs text-muted-foreground">
                  正在刷新筛选项缓存...
                </div>
              )}

              {mode === 'blueprint' && filters && (
                <div className="grid grid-cols-2 gap-4">
                  {filters.grades && (
                    <div>
                      <label className="text-sm font-medium mb-1.5 block">年级</label>
                      <Select value={gradeId} onValueChange={setGradeId}>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="全部年级" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">全部年级</SelectItem>
                          {filters.grades.map((g) => (
                            <SelectItem key={String(g.id)} value={String(g.id)}>
                              {g.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  {filters.textbookVersions && (
                    <div>
                      <label className="text-sm font-medium mb-1.5 block">教材版本</label>
                      <Select value={textbookVersionId} onValueChange={setTextbookVersionId}>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="全部版本" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">全部版本</SelectItem>
                          {filters.textbookVersions.map((v) => (
                            <SelectItem key={String(v.id)} value={String(v.id)}>
                              {v.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {mode === 'blueprint' ? (
            <>
              <Card className="surface-raised">
                <CardHeader className="flex flex-row items-center justify-between pb-3">
                  <div className="flex items-center gap-2">
                    <Layers className="h-5 w-5 text-muted-foreground" />
                    <CardTitle className="text-base">题型配置</CardTitle>
                  </div>
                  <div className="flex items-center gap-3 text-sm">
                    <Badge variant="secondary" className="font-normal">
                      {totalQuestions} 题
                    </Badge>
                    <Badge variant="secondary" className="font-normal">
                      {totalScore} 分
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-1 mb-4">
                    <AnimatePresence mode="popLayout">
                      {slots.map((slot, index) => (
                        <SlotEditor
                          key={slot.id}
                          slot={slot}
                          onUpdate={(s) => handleUpdateSlot(index, s)}
                          onRemove={() => handleRemoveSlot(index)}
                        />
                      ))}
                    </AnimatePresence>

                    {slots.length === 0 && (
                      <div className="text-center py-8 text-muted-foreground text-sm border border-dashed rounded-lg">
                        暂无题型，请添加
                      </div>
                    )}
                  </div>

                  <div className="relative">
                    <Button
                      variant="outline"
                      className="w-full justify-center gap-2 border-dashed hover:border-solid hover:bg-muted/50"
                      onClick={() => setShowQuestionTypes(!showQuestionTypes)}
                    >
                      <Plus className="h-4 w-4" />
                      添加题型
                      <ChevronDown className={cn('h-4 w-4 transition-transform', showQuestionTypes && 'rotate-180')} />
                    </Button>

                    <AnimatePresence>
                      {showQuestionTypes && (
                        <motion.div
                          initial={{ opacity: 0, y: -10 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -10 }}
                          className="absolute top-full left-0 right-0 mt-2 p-2 bg-popover border border-border rounded-lg shadow-lg z-10"
                        >
                          <div className="grid grid-cols-3 gap-2">
                            {defaultQuestionTypes.map((type) => (
                              <Button
                                key={type.id}
                                variant="ghost"
                                className="justify-start h-9"
                                onClick={() => handleAddSlot(type)}
                              >
                                {type.name}
                              </Button>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </CardContent>
              </Card>

              <div className="flex items-center gap-3 pt-4 border-t border-border">
                <div className="flex-1 flex items-center gap-2">
                  <Input
                    placeholder="蓝图名称"
                    value={blueprintName}
                    onChange={(e) => setBlueprintName(e.target.value)}
                    className="max-w-[240px]"
                  />
                  <Button
                    variant="ghost"
                    onClick={handleSaveBlueprint}
                    disabled={!blueprintName || !subject || slots.length === 0 || isSaving}
                  >
                    <Save className="h-4 w-4 mr-2" />
                    保存
                  </Button>
                </div>

                {isComposing ? (
                  <Button variant="destructive" onClick={pause} className="w-32">
                    <Pause className="h-4 w-4 mr-2" />
                    暂停
                  </Button>
                ) : isPaused ? (
                  <Button onClick={resume} className="w-32 bg-primary text-primary-foreground hover:bg-primary/90">
                    <Play className="h-4 w-4 mr-2" />
                    继续
                  </Button>
                ) : (
                  <Button
                    onClick={handleCompose}
                    disabled={!subject || slots.length === 0}
                    className="w-32 bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
                  >
                    {isComposing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <FileText className="h-4 w-4 mr-2" />}
                    开始组卷
                  </Button>
                )}
              </div>
            </>
          ) : (
            <>
              <Card className="surface-raised">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <Layers className="h-5 w-5 text-muted-foreground" />
                    <CardTitle className="text-base">一键组卷参数</CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">试卷标题（可选）</label>
                    <Input placeholder="留空将自动生成" value={blueprintName} onChange={(e) => setBlueprintName(e.target.value)} />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="text-sm font-medium mb-1.5 block">总分</label>
                      <Input
                        type="number"
                        min={30}
                        max={300}
                        value={oneClickTotalPoints}
                        onChange={(e) => setOneClickTotalPoints(parseInt(e.target.value) || 150)}
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-1.5 block">考试时长（分钟）</label>
                      <Input
                        type="number"
                        min={30}
                        max={240}
                        value={oneClickTimeLimit}
                        onChange={(e) => setOneClickTimeLimit(parseInt(e.target.value) || 120)}
                      />
                    </div>
                  </div>

                  <div>
                    <label className="text-sm font-medium mb-1.5 block">难题占比（{oneClickHardPct}%）</label>
                    <input
                      type="range"
                      min={0}
                      max={60}
                      value={oneClickHardPct}
                      onChange={(e) => setOneClickHardPct(parseInt(e.target.value) || 0)}
                      className="w-full accent-primary"
                    />
                    <div className="mt-1 text-xs text-muted-foreground">剩余比例会按“简单 40% / 中等 60%”自动分配。</div>
                  </div>

                  <div className="flex items-center gap-2">
                    <input
                      id="one-click-use-archive"
                      type="checkbox"
                      checked={oneClickUseArchive}
                      onChange={(e) => setOneClickUseArchive(e.target.checked)}
                      className="h-4 w-4"
                    />
                    <label htmlFor="one-click-use-archive" className="text-sm text-muted-foreground">
                      使用最近一次自学资料作为素材（如果存在）
                    </label>
                  </div>

                  {oneClickError ? (
                    <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                      {oneClickError}
                    </div>
                  ) : null}
                </CardContent>
              </Card>

              <div className="flex items-center gap-3 pt-4 border-t border-border">
                <div className="flex-1 flex items-center gap-2">
                  <Badge variant="secondary" className="font-normal">
                    进度 {Math.round(oneClickProgress)}%
                  </Badge>
                  {oneClickTaskId ? (
                    <Badge variant="outline" className="font-normal">
                      task={oneClickTaskId}
                    </Badge>
                  ) : null}
                </div>

                {isGeneratingFull ? (
                  <Button variant="destructive" onClick={handleStopGenerateFull} className="w-32">
                    <Square className="h-4 w-4 mr-2" />
                    停止
                  </Button>
                ) : (
                  <Button
                    onClick={handleGenerateFull}
                    disabled={!subject}
                    className="w-32 bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
                  >
                    <FileText className="h-4 w-4 mr-2" />
                    一键生成
                  </Button>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Right Panel: Preview & Timeline */}
      <div className="col-span-5 h-full bg-sidebar-background border-l border-border flex flex-col overflow-hidden">
        <div className="p-6 border-b border-border">
          <h3 className="font-semibold mb-4 flex items-center gap-2">
            <Loader2 className={cn("h-4 w-4", ((mode === 'blueprint' && isComposing) || (mode === 'one_click' && isGeneratingFull)) && "animate-spin")} />
            任务执行
          </h3>

          {mode === 'blueprint' ? (
            taskId ? (
              <TaskProgressHeader taskId={taskId} compact />
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>进度</span>
                  <span>{Math.round(progressPct)}%</span>
                </div>
                <Progress value={progressPct} className="h-2" />
              </div>
            )
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>进度</span>
                <span>{Math.round(oneClickProgress)}%</span>
              </div>
              <Progress value={oneClickProgress} className="h-2" />
            </div>
          )}
          </div>

        <ScrollArea className="flex-1">
          <div className="p-6">
            {mode === 'blueprint' && result ? (
              <div className="text-center py-10">
                <div className="h-16 w-16 bg-green-100 dark:bg-green-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
                  <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
                </div>
                <h3 className="text-lg font-medium mb-2">组卷完成</h3>
                <p className="text-muted-foreground mb-6">
                  已生成试卷，包含 {result.questions.length} 道题目
                </p>

                {slotShortfalls.length > 0 && (
                  <div className="mx-auto max-w-md mb-6 rounded-xl border border-amber-200/60 bg-amber-50/60 dark:border-amber-900/40 dark:bg-amber-900/10 p-4 text-left">
                    <div className="flex items-center gap-2 font-medium text-amber-900 dark:text-amber-200 mb-2">
                      <AlertTriangle className="h-4 w-4" />
                      槽位缺题提示
                    </div>
                    <div className="text-xs text-amber-900/80 dark:text-amber-200/80 space-y-1">
                      {slotShortfalls.slice(0, 6).map((s) => (
                        <div key={s.slotIndex}>
                          槽位 #{s.slotIndex + 1}：{s.questionType || '题型'} × {s.difficulty || '难度'}，缺 {s.requested - s.selected} 题
                        </div>
                      ))}
                      {slotShortfalls.length > 6 && <div>… 共 {slotShortfalls.length} 个槽位缺题</div>}
                    </div>
                    <div className="mt-3 flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        className="bg-background"
                        onClick={handleFillShortfalls}
                        disabled={isComposing}
                      >
                        一键重试补齐
                      </Button>
                    </div>
                  </div>
                )}
                <Button asChild className="gap-2">
                  <Link to={`/papers/${result.id}`}>
                    查看试卷 <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              </div>
            ) : mode === 'one_click' && oneClickResult ? (
              <div className="text-center py-10">
                <div className="h-16 w-16 bg-green-100 dark:bg-green-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
                  <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
                </div>
                <h3 className="text-lg font-medium mb-2">一键组卷完成</h3>
                <p className="text-muted-foreground mb-6">
                  已生成试卷，包含 {oneClickResult.questionCount} 道题目
                </p>
                <Button asChild className="gap-2">
                  <Link to={`/papers/${oneClickResult.paperId}`}>
                    查看试卷 <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              </div>
            ) : (
              <TaskTimeline steps={mode === 'blueprint' ? taskSteps : oneClickSteps} />
            )}
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
