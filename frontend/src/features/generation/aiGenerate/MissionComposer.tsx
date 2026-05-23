import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type TouchEvent as ReactTouchEvent,
} from 'react'
import { ChevronDown, GripHorizontal, PauseCircle, SendHorizontal, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import type { AiGenerateSessionMode } from '@/features/generation/aiGenerate/types'

type SubjectOption = {
  id: number | string
  code: string
  name: string
}

interface MissionComposerProps {
  missionText: string
  subject: string
  count: string
  difficulty: string
  questionType: string
  useStudyArchive: boolean
  useReferenceQuestions: boolean
  referenceSource: 'any' | 'gaokao' | 'mock' | 'joint' | string
  referenceYearRange: 'all' | '3' | '5' | string
  mode: AiGenerateSessionMode
  subjects: SubjectOption[]
  isGenerating: boolean
  primaryActionLabel?: string
  canStop?: boolean
  selectedKnowledgeCount?: number
  onMissionTextChange: (value: string) => void
  onSubjectChange: (value: string) => void
  onCountChange: (value: string) => void
  onDifficultyChange: (value: string) => void
  onQuestionTypeChange: (value: string) => void
  onUseStudyArchiveChange: (value: boolean) => void
  onUseReferenceQuestionsChange: (value: boolean) => void
  onReferenceSourceChange: (value: string) => void
  onReferenceYearRangeChange: (value: string) => void
  onModeChange: (value: AiGenerateSessionMode) => void
  onGenerate: () => void
  onStop?: () => void
}

const MIN_MISSION_HEIGHT = 124
const MAX_MISSION_HEIGHT = 320
type ResizeInputMode = 'mouse' | 'touch'

export function MissionComposer(props: MissionComposerProps) {
  const {
    missionText,
    subject,
    count,
    difficulty,
    questionType,
    useStudyArchive,
    useReferenceQuestions,
    referenceSource,
    referenceYearRange,
    mode,
    subjects,
    isGenerating,
    primaryActionLabel,
    canStop = false,
    selectedKnowledgeCount = 0,
    onMissionTextChange,
    onSubjectChange,
    onCountChange,
    onDifficultyChange,
    onQuestionTypeChange,
    onUseStudyArchiveChange,
    onUseReferenceQuestionsChange,
    onReferenceSourceChange,
    onReferenceYearRangeChange,
    onModeChange,
    onGenerate,
    onStop,
  } = props

  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [missionHeight, setMissionHeight] = useState(MIN_MISSION_HEIGHT)
  const [resizing, setResizing] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const dragStartYRef = useRef(0)
  const dragStartHeightRef = useRef(MIN_MISSION_HEIGHT)
  const resizeModeRef = useRef<ResizeInputMode | null>(null)

  useEffect(() => {
    if (!resizing) return

    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'

    const updateMissionHeight = (clientY: number) => {
      const nextHeight = dragStartHeightRef.current + (clientY - dragStartYRef.current)
      setMissionHeight(Math.max(MIN_MISSION_HEIGHT, Math.min(MAX_MISSION_HEIGHT, nextHeight)))
    }

    const onMouseMove = (event: MouseEvent) => {
      if (resizeModeRef.current !== 'mouse') return
      updateMissionHeight(event.clientY)
    }

    const onTouchMove = (event: TouchEvent) => {
      if (resizeModeRef.current !== 'touch') return
      const touch = event.touches[0]
      if (!touch) return
      event.preventDefault()
      updateMissionHeight(touch.clientY)
    }

    const stopResize = () => {
      resizeModeRef.current = null
      setResizing(false)
    }

    const stopMouseResize = () => {
      if (resizeModeRef.current !== 'mouse') return
      stopResize()
    }

    const stopTouchResize = () => {
      if (resizeModeRef.current !== 'touch') return
      stopResize()
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('touchmove', onTouchMove, { passive: false })
    document.addEventListener('mouseup', stopMouseResize)
    document.addEventListener('touchend', stopTouchResize)
    document.addEventListener('touchcancel', stopTouchResize)

    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('touchmove', onTouchMove)
      document.removeEventListener('mouseup', stopMouseResize)
      document.removeEventListener('touchend', stopTouchResize)
      document.removeEventListener('touchcancel', stopTouchResize)
    }
  }, [resizing])

  const beginResize = useCallback(
    (clientY: number, modeInput: ResizeInputMode) => {
      resizeModeRef.current = modeInput
      dragStartYRef.current = clientY

      const currentHeight =
        textareaRef.current?.getBoundingClientRect().height ||
        textareaRef.current?.offsetHeight ||
        missionHeight ||
        MIN_MISSION_HEIGHT

      dragStartHeightRef.current = Math.max(MIN_MISSION_HEIGHT, currentHeight)
      setResizing(true)
    },
    [missionHeight]
  )

  const handleMouseResizeStart = useCallback(
    (event: ReactMouseEvent<HTMLButtonElement>) => {
      event.preventDefault()
      beginResize(event.clientY, 'mouse')
    },
    [beginResize]
  )

  const handleTouchResizeStart = useCallback(
    (event: ReactTouchEvent<HTMLButtonElement>) => {
      const touch = event.touches[0]
      if (!touch) return
      event.preventDefault()
      beginResize(touch.clientY, 'touch')
    },
    [beginResize]
  )

  const adjustMissionHeight = useCallback((delta: number) => {
    setMissionHeight((prev) => Math.max(MIN_MISSION_HEIGHT, Math.min(MAX_MISSION_HEIGHT, prev + delta)))
  }, [])

  const actionLabel = primaryActionLabel || (isGenerating ? '生成中' : '开始生成')

  return (
    <section className="overflow-hidden rounded-[30px] border border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(245,240,229,0.92))] shadow-[0_24px_70px_rgba(30,33,45,0.08)] dark:bg-[linear-gradient(180deg,rgba(24,26,40,0.96),rgba(16,18,28,0.94))] dark:shadow-[0_28px_90px_rgba(0,0,0,0.58)]">
      <div className="flex flex-col gap-5 p-5 lg:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Sparkles className="h-4 w-4 text-muted-foreground" />
            出题任务
            {selectedKnowledgeCount > 0 && (
              <Badge variant="outline" className="rounded-full">已选 {selectedKnowledgeCount} 个知识点</Badge>
            )}
            <Badge variant="outline" className="rounded-full">
              {mode === 'infinite' ? '无限模式' : '标准模式'}
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            {canStop && (
              <Button type="button" variant="outline" size="sm" className="rounded-full" onClick={onStop}>
                <PauseCircle className="h-4 w-4" />
                停止追加
              </Button>
            )}
            <Button type="button" className="rounded-full" disabled={isGenerating} onClick={onGenerate}>
              <SendHorizontal className="h-4 w-4" />
              {actionLabel}
            </Button>
          </div>
        </div>

        <div className="relative rounded-[28px] border border-border/70 bg-background/85 p-4 shadow-sm">
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>支持自然语言任务描述</span>
            <span>·</span>
            <span>{subject || '未选择学科'}</span>
            <span>·</span>
            <span>{difficulty || '难度不限'}</span>
            <span>·</span>
            <span>{count || '5'} 题</span>
          </div>
          <Textarea
            ref={textareaRef}
            aria-label="出题任务描述"
            value={missionText}
            onChange={(event) => onMissionTextChange(event.target.value)}
            style={{ height: `${missionHeight}px` }}
            className="min-h-0 resize-none rounded-[24px] border-border/70 bg-background px-5 py-5 pb-10 text-base leading-7 text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.9)] dark:bg-card/80 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]"
            placeholder="例如：沿着函数单调性继续出 3 道压轴变式题，优先覆盖导数与分类讨论，审查不过的题不要自动确认。"
          />
          <div className="absolute right-16 bottom-7 z-10 inline-flex items-center gap-1">
            <button
              type="button"
              aria-label="减小任务输入框高度"
              className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-border/70 bg-background/92 text-xs font-semibold text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-foreground dark:bg-card/70"
              onClick={() => adjustMissionHeight(-24)}
            >
              -
            </button>
            <button
              type="button"
              aria-label="增大任务输入框高度"
              className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-border/70 bg-background/92 text-xs font-semibold text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-foreground dark:bg-card/70"
              onClick={() => adjustMissionHeight(24)}
            >
              +
            </button>
          </div>
          <button
            type="button"
            aria-label="调整任务输入框高度"
            className="absolute right-4 bottom-7 z-10 inline-flex h-6 w-10 touch-none cursor-row-resize items-center justify-center rounded-full border border-border/70 bg-background/92 text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-foreground dark:bg-card/70"
            onMouseDown={handleMouseResizeStart}
            onTouchStart={handleTouchResizeStart}
          >
            <GripHorizontal className="h-4 w-4" />
          </button>
          <div className="mt-3 rounded-[20px] border border-blue-200/80 bg-blue-50/70 px-4 py-3 text-sm text-blue-900 dark:border-sky-800/60 dark:bg-sky-950/35 dark:text-sky-100">
            <div className="font-medium">LaTeX 公式规范</div>
            <div className="mt-1 leading-6 text-blue-900/80 dark:text-sky-100/80">
              所有数学公式都要使用可渲染标记。例如行内写成 <code>{'\\(x^2+1\\)'}</code>，
              独立公式写成 <code>{'\\[x^2-1=0\\]'}</code>。
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            className="rounded-full"
            onClick={() => setAdvancedOpen((value) => !value)}
          >
            高级控制
            <ChevronDown className={`h-4 w-4 transition-transform ${advancedOpen ? 'rotate-180' : ''}`} />
          </Button>
          <div className="text-sm text-muted-foreground">
            {subject || '未选择学科'} · {difficulty || '难度不限'} · {count || '5'} 题 · {questionType || '题型不限'} ·{' '}
            {useStudyArchive ? '引用资料' : '不引用资料'} ·{' '}
            {useReferenceQuestions ? `参考真题·${referenceSource === 'gaokao' ? '高考' : referenceSource === 'mock' ? '模考' : referenceSource === 'joint' ? '联考' : '不限'}·${referenceYearRange === '3' ? '近3年' : referenceYearRange === '5' ? '近5年' : '不限'}` : '不参考真题'}
          </div>
        </div>

        {advancedOpen ? (
          <div className="grid gap-4 rounded-[28px] border border-border/70 bg-background/78 p-4 lg:grid-cols-2 xl:grid-cols-6">
            <div className="space-y-2">
              <label htmlFor="ai-generate-subject" className="text-sm font-medium">
                学科
              </label>
              <Select value={subject} onValueChange={onSubjectChange}>
                <SelectTrigger id="ai-generate-subject" aria-label="学科" className="rounded-2xl">
                  <SelectValue placeholder="选择学科" />
                </SelectTrigger>
                <SelectContent>
                  {subjects.map((item) => (
                    <SelectItem key={String(item.id)} value={item.code}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <label htmlFor="ai-generate-mode" className="text-sm font-medium">
                模式
              </label>
              <Select value={mode} onValueChange={(value) => onModeChange(value as AiGenerateSessionMode)}>
                <SelectTrigger id="ai-generate-mode" aria-label="模式" className="rounded-2xl">
                  <SelectValue placeholder="选择模式" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="standard">标准模式</SelectItem>
                  <SelectItem value="infinite">无限模式</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <label htmlFor="ai-generate-count" className="text-sm font-medium">
                题量
              </label>
              <Input
                id="ai-generate-count"
                aria-label="题量"
                value={count}
                onChange={(event) => onCountChange(event.target.value)}
                className="rounded-2xl"
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="ai-generate-difficulty" className="text-sm font-medium">
                难度
              </label>
              <Select
                value={difficulty || '__any__'}
                onValueChange={(value) => onDifficultyChange(value === '__any__' ? '' : value)}
              >
                <SelectTrigger id="ai-generate-difficulty" aria-label="难度" className="rounded-2xl">
                  <SelectValue placeholder="难度不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__any__">难度不限</SelectItem>
                  <SelectItem value="简单">简单</SelectItem>
                  <SelectItem value="中等">中等</SelectItem>
                  <SelectItem value="困难">困难</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <label htmlFor="ai-generate-type" className="text-sm font-medium">
                题型
              </label>
              <Input
                id="ai-generate-type"
                aria-label="题型"
                value={questionType}
                onChange={(event) => onQuestionTypeChange(event.target.value)}
                placeholder="例如：选择题 / 解答题"
                className="rounded-2xl"
              />
            </div>

            <div className="space-y-2">
              <label htmlFor="ai-generate-reference-source" className="text-sm font-medium">
                参考来源
              </label>
              <Select value={referenceSource || 'any'} onValueChange={onReferenceSourceChange} disabled={!useReferenceQuestions}>
                <SelectTrigger id="ai-generate-reference-source" aria-label="参考来源" className="rounded-2xl">
                  <SelectValue placeholder="参考来源不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">不限</SelectItem>
                  <SelectItem value="gaokao">高考真题</SelectItem>
                  <SelectItem value="mock">模考题</SelectItem>
                  <SelectItem value="joint">联考题</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <label htmlFor="ai-generate-reference-year-range" className="text-sm font-medium">
                参考年份
              </label>
              <Select value={referenceYearRange || 'all'} onValueChange={onReferenceYearRangeChange} disabled={!useReferenceQuestions}>
                <SelectTrigger id="ai-generate-reference-year-range" aria-label="参考年份" className="rounded-2xl">
                  <SelectValue placeholder="参考年份不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">不限</SelectItem>
                  <SelectItem value="3">近3年</SelectItem>
                  <SelectItem value="5">近5年</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="rounded-[24px] border border-border/70 bg-background/76 p-4 xl:col-span-3">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-sm font-medium">引用自学资料</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    从近期 Study Archive 中提取上下文，提升题目风格与知识点命中率。
                  </div>
                </div>
                <Switch checked={useStudyArchive} onCheckedChange={onUseStudyArchiveChange} />
              </div>
            </div>

            <div className="rounded-[24px] border border-border/70 bg-background/76 p-4 xl:col-span-3">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-sm font-medium">参考真题</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    在素材整理后补抓真实试题样本，提炼出题模式与难度标定；关闭后会跳过参考题学习阶段。
                  </div>
                </div>
                <Switch checked={useReferenceQuestions} onCheckedChange={onUseReferenceQuestionsChange} />
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  )
}
