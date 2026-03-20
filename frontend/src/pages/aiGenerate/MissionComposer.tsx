import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type TouchEvent as ReactTouchEvent,
} from 'react'
import { ChevronDown, GripHorizontal, Sparkles, Wand2 } from 'lucide-react'
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
import { LATEX_RULE_TEXT } from '@/pages/aiGenerate/latexRules'

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
  subjects: SubjectOption[]
  isGenerating: boolean
  onMissionTextChange: (value: string) => void
  onSubjectChange: (value: string) => void
  onCountChange: (value: string) => void
  onDifficultyChange: (value: string) => void
  onQuestionTypeChange: (value: string) => void
  onUseStudyArchiveChange: (value: boolean) => void
  onGenerate: () => void
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
    subjects,
    isGenerating,
    onMissionTextChange,
    onSubjectChange,
    onCountChange,
    onDifficultyChange,
    onQuestionTypeChange,
    onUseStudyArchiveChange,
    onGenerate,
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

  const beginResize = useCallback((clientY: number, mode: ResizeInputMode) => {
    resizeModeRef.current = mode
    dragStartYRef.current = clientY

    const currentHeight =
      textareaRef.current?.getBoundingClientRect().height ||
      textareaRef.current?.offsetHeight ||
      missionHeight ||
      MIN_MISSION_HEIGHT

    dragStartHeightRef.current = Math.max(MIN_MISSION_HEIGHT, currentHeight)
    setResizing(true)
  }, [missionHeight])

  const handleMouseResizeStart = useCallback((event: ReactMouseEvent<HTMLButtonElement>) => {
    event.preventDefault()
    beginResize(event.clientY, 'mouse')
  }, [beginResize])

  const handleTouchResizeStart = useCallback((event: ReactTouchEvent<HTMLButtonElement>) => {
    const touch = event.touches[0]
    if (!touch) return
    event.preventDefault()
    beginResize(touch.clientY, 'touch')
  }, [beginResize])

  const adjustMissionHeight = useCallback((delta: number) => {
    setMissionHeight((prev) => Math.max(MIN_MISSION_HEIGHT, Math.min(MAX_MISSION_HEIGHT, prev + delta)))
  }, [])

  return (
    <section className="overflow-hidden rounded-[32px] border border-border/70 bg-background/80 shadow-[0_30px_100px_rgba(33,38,56,0.08)] backdrop-blur dark:bg-[linear-gradient(180deg,rgba(18,20,30,0.88),rgba(12,14,20,0.82))] dark:shadow-[0_30px_110px_rgba(0,0,0,0.6)]">
      <div className="flex flex-col gap-6 p-6 lg:p-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-background/80 px-3 py-1 text-xs font-medium text-muted-foreground">
              <Sparkles className="h-3.5 w-3.5" />
              Editorial AI Studio
            </div>
            <div className="space-y-2">
              <h1 className="text-3xl font-semibold tracking-tight lg:text-4xl">AI 出题工作台</h1>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground lg:text-base">
                像给 AI 下创作任务一样描述你的需求，题目会在下方按题干、答案、解析逐步展开。
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button type="button" size="lg" className="min-w-32 rounded-full" disabled={isGenerating} onClick={onGenerate}>
              <Wand2 className="h-4 w-4" />
              {isGenerating ? '生成中' : '开始生成'}
            </Button>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.8fr)]">
          <div className="rounded-[28px] border border-border/60 bg-[linear-gradient(180deg,rgba(255,255,255,0.92),rgba(252,249,242,0.95))] p-4 shadow-sm dark:bg-[linear-gradient(180deg,rgba(30,32,46,0.92),rgba(18,20,30,0.92))] lg:p-5">
            <div className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">Mission Bar</div>
            <div className="relative mt-3">
              <Textarea
                ref={textareaRef}
                aria-label="出题任务描述"
                value={missionText}
                onChange={(event) => onMissionTextChange(event.target.value)}
                style={{ height: `${missionHeight}px` }}
                className="min-h-0 resize-none rounded-[24px] border-border/70 bg-background px-5 py-5 pb-10 text-base leading-7 text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.9)] dark:bg-card/80 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]"
                placeholder="例如：为高一数学生成 5 道函数单调性中等难度题，包含答案和解析，并优先参考最近自学资料。"
              />
              <div className="absolute right-16 bottom-3 z-10 inline-flex items-center gap-1">
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
                className="absolute right-4 bottom-3 z-10 inline-flex h-6 w-10 touch-none cursor-row-resize items-center justify-center rounded-full border border-border/70 bg-background/92 text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-foreground dark:bg-card/70"
                onMouseDown={handleMouseResizeStart}
                onTouchStart={handleTouchResizeStart}
              >
                <GripHorizontal className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-3 rounded-[20px] border border-blue-200/80 bg-blue-50/70 px-4 py-3 text-sm text-blue-900 dark:border-sky-800/60 dark:bg-sky-950/35 dark:text-sky-100">
              <div className="font-medium">LaTeX 公式规范</div>
              <div className="mt-1 leading-6 text-blue-900/80 dark:text-sky-100/80">
                {LATEX_RULE_TEXT} 例如行内写成 <code>{'\\(x^2+1\\)'}</code>，独立公式写成 <code>{'\\[x^2-1=0\\]'}</code>。
              </div>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
            <div className="rounded-[24px] border border-border/70 bg-background/88 p-4 shadow-sm">
              <div className="text-sm font-medium text-muted-foreground">学科</div>
              <div className="mt-2 text-xl font-semibold">{subject || '未设置'}</div>
            </div>
            <div className="rounded-[24px] border border-border/70 bg-background/88 p-4 shadow-sm">
              <div className="text-sm font-medium text-muted-foreground">题量</div>
              <div className="mt-2 text-xl font-semibold">{count || '5'} 题</div>
            </div>
            <div className="rounded-[24px] border border-border/70 bg-background/88 p-4 shadow-sm">
              <div className="text-sm font-medium text-muted-foreground">引用资料</div>
              <div className="mt-2 text-xl font-semibold">{useStudyArchive ? '已启用' : '未启用'}</div>
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
            {subject || '未选择学科'} · {difficulty || '难度不限'} · {count || '5'} 题 · {questionType || '题型不限'}
          </div>
        </div>

        {advancedOpen && (
          <div className="grid gap-4 rounded-[28px] border border-border/70 bg-background/78 p-4 lg:grid-cols-2 xl:grid-cols-4">
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
              <Select value={difficulty || '__any__'} onValueChange={(value) => onDifficultyChange(value === '__any__' ? '' : value)}>
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

            <div className="rounded-[24px] border border-border/70 bg-background/76 p-4 xl:col-span-4">
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
          </div>
        )}
      </div>
    </section>
  )
}
