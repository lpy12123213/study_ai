import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import {
  BookOpenCheck,
  Clock,
  Loader2,
  Plus,
  Send,
  Sparkles,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  GripVertical,
  Layers,
  CheckCircle2,
  Circle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { BrandMark } from '@/components/shared/BrandMark'
import { useSubjects } from '@/hooks/useSubjects'
import { fetchSSE, resolveApiResourceUrl } from '@/api/client'
import { useConversationStore } from '@/stores/useConversationStore'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn, generateId } from '@/lib/utils'
import type { ConversationItem, Message, Subject, TaskStep } from '@/types'

const grades = [
  '一年级', '二年级', '三年级', '四年级', '五年级', '六年级',
  '七年级', '八年级', '九年级', '高一', '高二', '高三',
]

type LessonPlanAgentEvent =
  | { event: 'thinking'; data: { content?: unknown } }
  | { event: 'tool_call'; data: { step_id?: unknown; name?: unknown; title?: unknown; arguments?: unknown } }
  | { event: 'tool_result'; data: { step_id?: unknown; name?: unknown; title?: unknown; success?: unknown; elapsed_ms?: unknown; output?: unknown; error?: unknown } }
  | { event: 'subagent_start'; data: { knowledge_point?: unknown; index?: unknown; total?: unknown; content?: unknown } }
  | { event: 'subagent_end'; data: { knowledge_point?: unknown; index?: unknown; total?: unknown; content?: unknown } }
  | { event: 'done'; data: { material?: unknown } }
  | { event: 'error'; data: { message?: unknown } }
  | { event: string; data?: unknown }

function toText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function stripAll(haystack: string, needle: string): string {
  if (!needle) return haystack
  let result = haystack
  while (result.includes(needle)) result = result.replace(needle, '')
  return result
}

function getStageByGrade(grade: string | null): '小学' | '初中' | '高中' | '' {
  if (!grade) return ''
  const g = grade.trim()
  if (/^[一二三四五六]年级/.test(g)) return '小学'
  if (/^[七八九]年级/.test(g)) return '初中'
  if (/^高[一二三]/.test(g)) return '高中'
  return ''
}

function extractGradeFromText(text: string): string | null {
  const t = (text || '').trim()
  for (const g of grades) {
    if (t.includes(g)) return g
  }
  const m = t.match(/(小学|初中|高中|初一|初二|初三)/)
  if (m) {
    const map: Record<string, string> = {
      '初一': '七年级', '初二': '八年级', '初三': '九年级',
    }
    return map[m[1]] || null
  }
  return null
}

function extractDurationMinutesFromText(text: string): number | null {
  const m = (text || '').match(/(\d{2,3})\s*(分钟|min)/i)
  if (!m) return null
  const n = parseInt(m[1], 10)
  return n >= 15 && n <= 180 ? n : null
}

function extractSubjectFromText(
  text: string, subjects: Subject[] | undefined, grade: string | null
): string | null {
  const list = subjects ?? []
  const t = text || ''

  const direct = list
    .map((s) => s?.name)
    .filter((name): name is string => typeof name === 'string' && !!name)
    .filter((name) => t.includes(name))
    .sort((a, b) => b.length - a.length)[0]
  if (direct) return direct

  const stage = getStageByGrade(grade)
  const stageOrder = stage ? [stage, '高中', '初中', '小学'] : ['高中', '初中', '小学']

  const aliasKeys = [
    '语文', '数学', '英语', '物理', '化学', '生物',
    '政治', '历史', '地理', '道德与法治', '科学',
  ]

  const alias = aliasKeys.find((k) => t.includes(k))
  if (!alias) return null

  const candidates = stageOrder.map((s) => `${s}${alias}`)
  for (const c of candidates) {
    if (list.some((x) => x?.name === c)) return c
  }

  const fuzzy = list
    .map((s) => s?.name)
    .filter((name): name is string => typeof name === 'string')
    .find((name) => name.includes(alias))
  return fuzzy ?? null
}

function extractTopicFromText(
  text: string, subject: string | null, grade: string | null
): string {
  const raw = (text || '').trim()
  if (!raw) return ''

  const book = raw.match(/《([^》]{2,80})》/)?.[1]?.trim()
  if (book) return book

  const byKey = raw.match(/(?:课题|主题|标题|topic)\s*[:：]\s*(.+)/i)?.[1]
  if (byKey) return byKey.split('\n')[0].trim()

  let t = raw
  if (subject) t = stripAll(t, subject)
  if (grade) t = stripAll(t, grade)
  t = t.replace(/\d{1,3}\s*(分钟|min)/gi, '')
  t = t
    .replace(/[，。；、,.!！?？]/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/(帮我|请|生成|写|做|来一份|一份|一个|教案|教学|设计|详细|完整版|课程|课时)/g, '')
    .trim()

  if (!t) return ''
  return t.length > 40 ? t.slice(0, 40).trim() : t
}

function toConversationTitle(text: string): string {
  const t = (text || '').trim()
  if (!t) return '新教案'
  return t.length > 18 ? `${t.slice(0, 18)}…` : t
}

// ── SubAgent activity tracking ──────────────────────────────────────

interface SubAgentActivity {
  knowledgePoint: string
  status: 'pending' | 'running' | 'completed'
  steps: TaskStep[]
}

// ── Small components ────────────────────────────────────────────────

function LessonPlanAttachment({ lessonPlanId }: { lessonPlanId: string }) {
  const plan = useLessonPlanStore((state) => state.getPlan(lessonPlanId))
  if (!plan) return null

  return (
    <div className="mt-4">
      <Link to={`/lesson-plans/${plan.id}`} className="block group">
        <div className="rounded-xl border border-border bg-card p-4 transition-all hover:shadow-md hover:border-primary/50">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                  <BookOpenCheck className="h-4 w-4" />
                </div>
                <div className="font-semibold truncate text-foreground">{plan.title}</div>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                <Badge variant="secondary" className="font-normal">{plan.subject}</Badge>
                <span>{plan.grade}</span>
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {plan.duration} 分钟
                </span>
              </div>
            </div>
            <div className="self-center opacity-0 group-hover:opacity-100 transition-opacity -translate-x-2 group-hover:translate-x-0 duration-200">
              <Button variant="ghost" size="icon">
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </Link>
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const [showSteps, setShowSteps] = useState(false)

  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex justify-end mb-6"
      >
        <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl bg-muted px-5 py-3 text-sm leading-6 text-foreground">
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>
      </motion.div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-2 mb-8 w-full"
    >
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
        <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center">
          <BrandMark size={12} />
        </div>
        <span>学习助手</span>
      </div>

      <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-7">
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{
            a: ({ href, children, ...props }) => {
              const url = typeof href === 'string' ? href : ''
              const isGenerated = url.startsWith('/api/media/generated/')
              const isDownload = isGenerated && /\.(md|pdf|tex)$/i.test(url)
              const className = isDownload
                ? 'inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground no-underline hover:bg-primary/90'
                : 'text-primary underline underline-offset-4 hover:opacity-90'

              return (
                <a
                  href={url}
                  className={className}
                  target={isDownload ? '_blank' : undefined}
                  rel={isDownload ? 'noreferrer' : undefined}
                  download={isDownload ? '' : undefined}
                  {...props}
                >
                  {children}
                </a>
              )
            },
          }}
        >
          {message.content}
        </ReactMarkdown>
      </div>

      {message.attachment?.type === 'lesson_plan' && (
        <LessonPlanAttachment lessonPlanId={message.attachment.lessonPlanId} />
      )}

      {message.steps && message.steps.length > 0 && (
        <div className="mt-3">
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs font-normal gap-1.5 bg-background hover:bg-muted/50"
            onClick={() => setShowSteps(!showSteps)}
          >
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            {showSteps ? '隐藏' : '查看'} {message.steps.length} 个思考步骤
            {showSteps ? <ChevronUp className="h-3 w-3 opacity-50" /> : <ChevronDown className="h-3 w-3 opacity-50" />}
          </Button>

          <AnimatePresence>
            {showSteps && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="mt-3 overflow-hidden rounded-lg border border-border bg-card"
              >
                <div className="p-4 bg-muted/30">
                  <TaskTimeline steps={message.steps} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  )
}

function WelcomeScreen({ onExampleClick }: { onExampleClick: (text: string) => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 animate-in fade-in duration-500">
      <div className="mb-10 flex flex-col items-center text-center space-y-6">
        <div className="h-20 w-20 rounded-3xl bg-gradient-to-br from-primary/5 to-primary/10 flex items-center justify-center ring-1 ring-border/50 shadow-sm">
          <BookOpenCheck className="h-10 w-10 text-primary" strokeWidth={1.5} />
        </div>
        <h2 className="text-2xl font-semibold tracking-tight">教案生成助手</h2>
        <p className="text-muted-foreground max-w-md">
          输入你的需求（建议包含学科/年级/课题/课时），我将为你生成一份详细的教学设计。
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full">
        {[
          { title: '函数与导数', desc: '高二数学：函数单调性与导数应用' },
          { title: '力学实验', desc: '高一物理：验证牛顿第二定律' },
          { title: '文言文阅读', desc: '高一语文：文言文断句与翻译' },
          { title: '化学反应速率', desc: '高二化学：影响反应速率的因素' },
        ].map((item) => (
          <button
            key={item.title}
            onClick={() => onExampleClick(item.desc)}
            className="group relative flex flex-col items-start p-4 h-auto text-left rounded-xl border bg-card hover:bg-accent/50 hover:border-accent transition-all duration-200 hover:-translate-y-0.5 shadow-sm hover:shadow-md"
          >
            <div className="mb-3 rounded-lg bg-muted p-2 group-hover:bg-background transition-colors">
              <BookOpenCheck className="h-4 w-4 text-muted-foreground group-hover:text-foreground" />
            </div>
            <div className="font-medium text-sm mb-1">{item.title}</div>
            <div className="text-xs text-muted-foreground line-clamp-2">{item.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── SubAgent Panel (right column) ───────────────────────────────────

function SubAgentPanel({ activities }: { activities: SubAgentActivity[] }) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [activities])

  if (activities.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-muted-foreground text-sm p-6">
        <Layers className="h-10 w-10 mb-3 opacity-30" />
        <p>等待知识点拆分…</p>
        <p className="text-xs mt-1 opacity-60">SubAgent 将逐个研究每个知识点</p>
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="h-full overflow-auto p-4 space-y-3">
      <div className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-2">
        <Layers className="h-3.5 w-3.5" />
        知识点研究进度（{activities.filter((a) => a.status === 'completed').length}/{activities.length}）
      </div>

      {activities.map((activity, i) => (
        <motion.div
          key={activity.knowledgePoint}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.05 }}
          className={cn(
            'rounded-lg border p-3 transition-all',
            activity.status === 'running' && 'border-primary/50 bg-primary/5 shadow-sm',
            activity.status === 'completed' && 'border-border bg-card',
            activity.status === 'pending' && 'border-border/50 bg-muted/30 opacity-60',
          )}
        >
          <div className="flex items-center gap-2 mb-2">
            {activity.status === 'completed' && (
              <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
            )}
            {activity.status === 'running' && (
              <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />
            )}
            {activity.status === 'pending' && (
              <Circle className="h-4 w-4 text-muted-foreground/40 shrink-0" />
            )}
            <span className="text-sm font-medium truncate">{activity.knowledgePoint}</span>
          </div>

          {activity.steps.length > 0 && activity.status !== 'pending' && (
            <div className="ml-6 space-y-1">
              {activity.steps.map((step) => (
                <div key={step.id} className="flex items-center gap-2 text-xs text-muted-foreground">
                  {step.status === 'completed' && <CheckCircle2 className="h-3 w-3 text-green-500/70 shrink-0" />}
                  {step.status === 'running' && <Loader2 className="h-3 w-3 text-primary animate-spin shrink-0" />}
                  {step.status === 'pending' && <Circle className="h-3 w-3 opacity-40 shrink-0" />}
                  <span className="truncate">{step.title}</span>
                </div>
              ))}
            </div>
          )}
        </motion.div>
      ))}
    </div>
  )
}

// ── Draggable divider ───────────────────────────────────────────────

function DraggableDivider({ onDrag }: { onDrag: (deltaX: number) => void }) {
  const dragging = useRef(false)
  const lastX = useRef(0)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    lastX.current = e.clientX
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragging.current) return
      const dx = ev.clientX - lastX.current
      lastX.current = ev.clientX
      onDrag(dx)
    }
    const onMouseUp = () => {
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [onDrag])

  return (
    <div
      className="w-2 shrink-0 cursor-col-resize flex items-center justify-center group hover:bg-primary/10 transition-colors relative z-10"
      onMouseDown={onMouseDown}
      role="separator"
      aria-orientation="vertical"
      tabIndex={0}
    >
      <GripVertical className="h-5 w-5 text-muted-foreground/30 group-hover:text-primary/50 transition-colors" />
    </div>
  )
}

// ── Main page component ─────────────────────────────────────────────

function LessonPlansPage() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const [input, setInput] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Split pane: left panel width ratio (0.25 to 0.75)
  const [leftRatio, setLeftRatio] = useState(0.38)

  // SubAgent activities for the right panel
  const [subAgentActivities, setSubAgentActivities] = useState<SubAgentActivity[]>([])

  const { data: subjects } = useSubjects()

  const conversations = useConversationStore((state) => state.conversations)
  const currentConversationId = useConversationStore((state) => state.currentConversationId)
  const addConversation = useConversationStore((state) => state.addConversation)
  const setCurrentConversation = useConversationStore((state) => state.setCurrentConversation)
  const updateConversation = useConversationStore((state) => state.updateConversation)
  const setMessages = useConversationStore((state) => state.setMessages)
  const addMessage = useConversationStore((state) => state.addMessage)

  const savePlan = useLessonPlanStore((state) => state.savePlan)
  const { startTask, addStep, updateStep, completeTask, failTask } = useTaskStore()

  const activeConversationId = useMemo(() => {
    if (!currentConversationId) return null
    const current = conversations.find((c) => c.id === currentConversationId)
    return current?.type === 'lesson_plan' ? currentConversationId : null
  }, [conversations, currentConversationId])

  const messages = useConversationStore((state) =>
    state.getMessages(activeConversationId ?? '')
  )

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages.length])

  const handleDrag = useCallback((deltaX: number) => {
    if (!containerRef.current) return
    const totalWidth = containerRef.current.offsetWidth
    if (totalWidth <= 0) return
    setLeftRatio((prev) => {
      const next = prev + deltaX / totalWidth
      return Math.max(0.2, Math.min(0.65, next))
    })
  }, [])

  const handleNewConversation = () => {
    const id = generateId()
    const now = new Date().toISOString()
    const item: ConversationItem = {
      id,
      title: '新教案',
      type: 'lesson_plan',
      createdAt: now,
      updatedAt: now,
      status: 'active',
      resumable: false,
    }
    addConversation(item)
    setCurrentConversation(id)
    setMessages(id, [])
    setInput('')
    setError(null)
    setSubAgentActivities([])
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const prompt = input.trim()
    if (!prompt || isGenerating) return

    const now = new Date().toISOString()

    let conversationId = activeConversationId
    if (!conversationId) {
      const inferredGrade = extractGradeFromText(prompt)
      const inferredSubject = extractSubjectFromText(prompt, subjects, inferredGrade)
      const inferredTopic = extractTopicFromText(prompt, inferredSubject, inferredGrade)

      conversationId = generateId()
      const conversation: ConversationItem = {
        id: conversationId,
        title: toConversationTitle(inferredTopic || prompt),
        type: 'lesson_plan',
        createdAt: now,
        updatedAt: now,
        status: 'active',
        resumable: false,
        progress: 0,
      }
      addConversation(conversation)
      setCurrentConversation(conversationId)
      setMessages(conversationId, [])
    } else {
      updateConversation(conversationId, { updatedAt: now, status: 'active' })
    }

    addMessage(conversationId, {
      id: generateId(),
      role: 'user',
      content: prompt,
      createdAt: now,
    })

    setInput('')
    setError(null)
    setSubAgentActivities([])

    const existingPlan = useLessonPlanStore.getState().getPlan(conversationId)

    const inferredGrade = extractGradeFromText(prompt)
    const resolvedGrade = (inferredGrade ?? existingPlan?.grade ?? '').trim()
    const inferredSubject = extractSubjectFromText(prompt, subjects, resolvedGrade || existingPlan?.grade || null)
    const resolvedSubject = (inferredSubject ?? existingPlan?.subject ?? '').trim()
    const inferredTopic = extractTopicFromText(prompt, resolvedSubject || null, resolvedGrade || null)
    const resolvedTopic = (inferredTopic || existingPlan?.title || '').trim()
    const resolvedDuration = extractDurationMinutesFromText(prompt) ?? existingPlan?.duration ?? 45
    const resolvedObjectives = existingPlan?.objectives ?? []
    const resolvedAdditional = prompt

    const missing: string[] = []
    if (!resolvedSubject) missing.push('学科')
    if (!resolvedGrade) missing.push('年级')
    if (!resolvedTopic) missing.push('课题')

    if (missing.length > 0) {
      addMessage(conversationId, {
        id: generateId(),
        role: 'assistant',
        createdAt: now,
        content:
          `为了生成教案，我还缺少：${missing.join('、')}。\n\n` +
          `请在消息里包含这些信息，例如：\n` +
          `"高中数学 高二 《函数单调性与导数应用》 45分钟 教案（互动式/含分层练习）"。`,
      })
      return
    }

    const titleCandidate = toConversationTitle(resolvedTopic)
    const current = conversations.find((c) => c.id === conversationId)
    if (!current || current.title.startsWith('新教案')) {
      updateConversation(conversationId, { title: titleCandidate, updatedAt: now })
    }

    const assistantMessageId = generateId()
    addMessage(conversationId, {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      createdAt: now,
      steps: [],
    })

    const taskId = `lesson-plan-${conversationId}-${Date.now()}`
    startTask(taskId)
    setIsGenerating(true)

    let done = false

    let assistantSteps: TaskStep[] = []
    let thinkingStepId: string | null = null
    let thinkingBuffer = ''

    // Track current subagent index for the right panel
    let currentSubAgentKP: string | null = null

    const syncSteps = () => {
      useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
        steps: assistantSteps,
      })
    }

    const addAssistantStep = (step: TaskStep) => {
      assistantSteps = [...assistantSteps, step]
      syncSteps()
    }

    const patchAssistantStep = (stepId: string, patch: Partial<TaskStep>) => {
      assistantSteps = assistantSteps.map((s) => (s.id === stepId ? { ...s, ...patch } : s))
      syncSteps()
    }

    void fetchSSE(
      '/lesson-plans/generate',
      {
        subject: resolvedSubject,
        grade: resolvedGrade,
        topic: resolvedTopic,
        duration_minutes: resolvedDuration,
        objectives: resolvedObjectives.length > 0 ? resolvedObjectives : undefined,
        additional_requirements: resolvedAdditional || undefined,
      },
      (data) => {
        const evt = data as LessonPlanAgentEvent
        const kind = typeof (evt as any)?.event === 'string' ? (evt as any).event : ''
        const payload = (evt as any)?.data

        if (kind === 'thinking') {
          const text = toText(payload?.content) || '思考中…'
          const t = new Date().toISOString()

          if (!thinkingStepId) {
            thinkingStepId = `thinking-${generateId()}`
            thinkingBuffer = ''
            const step: TaskStep = {
              id: thinkingStepId,
              title: '思考',
              status: 'running',
              startTime: t,
              toolName: 'thinking',
              output: '',
            }
            addAssistantStep(step)
            addStep(taskId, step)
          }

          thinkingBuffer = thinkingBuffer ? `${thinkingBuffer}\n${text}` : text
          patchAssistantStep(thinkingStepId, { output: thinkingBuffer })
          updateStep(taskId, thinkingStepId, { output: thinkingBuffer })

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 15 })
          return
        }

        if (kind === 'tool_call') {
          const name = toText(payload?.name) || 'tool'

          // Close the current thinking step when the agent starts executing tools.
          if (thinkingStepId) {
            const tThinking = new Date().toISOString()
            patchAssistantStep(thinkingStepId, { status: 'completed', endTime: tThinking })
            updateStep(taskId, thinkingStepId, { status: 'completed', endTime: tThinking })
            thinkingStepId = null
            thinkingBuffer = ''
          }

          const stepId = toText((payload as any)?.step_id) || generateId()
          const stepTitle = toText((payload as any)?.title)
          const t = new Date().toISOString()

          const step: TaskStep = {
            id: stepId,
            title: stepTitle || `调用工具：${name}`,
            status: 'running',
            startTime: t,
            toolName: name,
            input: (payload as any)?.arguments,
          }

          if (!assistantSteps.some((s) => s.id === stepId)) {
            addAssistantStep(step)
            addStep(taskId, step)
          } else {
            patchAssistantStep(stepId, step)
            updateStep(taskId, stepId, step)
          }

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 35 })

          // If this is a subagent tool call, add step to the current subagent activity
          if (currentSubAgentKP) {
            setSubAgentActivities((prev) =>
              prev.map((a) =>
                a.knowledgePoint === currentSubAgentKP
                  ? {
                      ...a,
                      steps: [
                        ...a.steps,
                        {
                          id: stepId,
                          title: stepTitle || `调用 ${name}`,
                          status: 'running' as const,
                          toolName: name,
                          startTime: t,
                        },
                      ],
                    }
                  : a
              )
            )
          }
          return
        }

        if (kind === 'tool_result') {
          const toolName = toText((payload as any)?.name) || ''
          const stepId = toText((payload as any)?.step_id)
          if (!stepId) return

          const success = (payload as any)?.success === true
          const out = (payload as any)?.output
          const err = toText((payload as any)?.error)
          const t = new Date().toISOString()

          patchAssistantStep(stepId, {
            status: success ? 'completed' : 'failed',
            endTime: t,
            output: out,
            error: err || undefined,
            toolName: toolName || undefined,
          })
          updateStep(taskId, stepId, {
            status: success ? 'completed' : 'failed',
            endTime: t,
            output: out,
            error: err || undefined,
          })

          // If split/review produced knowledge points, initialize the right panel list.
          if (
            (toolName === 'split_knowledge_points' || toolName === 'review_knowledge_points') &&
            out &&
            typeof out === 'object'
          ) {
            const kps = Array.isArray((out as any).knowledge_points)
              ? ((out as any).knowledge_points as string[])
              : []
            if (kps.length > 0) {
              setSubAgentActivities(
                kps.map((kp) => ({
                  knowledgePoint: kp,
                  status: 'pending' as const,
                  steps: [],
                }))
              )
            }
          }

          // Complete the running step in current subagent
          if (currentSubAgentKP) {
            setSubAgentActivities((prev) =>
              prev.map((a) =>
                a.knowledgePoint === currentSubAgentKP
                  ? {
                      ...a,
                      steps: a.steps.map((s) =>
                        s.id === stepId
                          ? {
                              ...s,
                              status: success ? ('completed' as const) : ('failed' as const),
                              endTime: t,
                            }
                          : s
                      ),
                    }
                  : a
              )
            )
          }

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 55 })
          return
        }

        if (kind === 'subagent_start') {
          const kp = toText(payload?.knowledge_point)
          currentSubAgentKP = kp || null

          // Mark this activity as running
          setSubAgentActivities((prev) =>
            prev.map((a) =>
              a.knowledgePoint === kp ? { ...a, status: 'running' as const } : a
            )
          )

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 45 })
          return
        }

        if (kind === 'subagent_end') {
          const kp = toText(payload?.knowledge_point)
          currentSubAgentKP = null

          // Mark this activity as completed
          setSubAgentActivities((prev) =>
            prev.map((a) =>
              a.knowledgePoint === kp
                ? {
                    ...a,
                    status: 'completed' as const,
                    steps: a.steps.map((s) =>
                      s.status === 'running'
                        ? { ...s, status: 'completed' as const, endTime: new Date().toISOString() }
                        : s
                    ),
                  }
                : a
            )
          )
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 70 })
          return
        }

        if (kind === 'done') {
          done = true

          const t = new Date().toISOString()
          if (thinkingStepId) {
            patchAssistantStep(thinkingStepId, { status: 'completed', endTime: t })
            updateStep(taskId, thinkingStepId, { status: 'completed', endTime: t })
          }

          const material = (payload as any)?.material as any
          const title = toText(material?.title) || resolvedTopic || '教案'
          const durationMinutes =
            typeof material?.duration_minutes === 'number' ? material.duration_minutes : resolvedDuration
          const mdUrl = toText(material?.md_url)
          const pdfUrl = toText(material?.pdf_url)
          const mdFilename = toText(material?.md_filename)
          const pdfFilename = toText(material?.pdf_filename)
          const mdHref = mdUrl ? resolveApiResourceUrl(mdUrl) : ''
          const pdfHref = pdfUrl ? resolveApiResourceUrl(pdfUrl) : ''

          const lines: string[] = [
            '已生成教案，可下载：',
            '',
            mdHref ? `- Markdown： [下载 Markdown](${mdHref})` : '- Markdown： （生成失败或未导出）',
            pdfHref ? `- PDF： [下载 PDF](${pdfHref})` : '- PDF： （生成失败或未编译）',
          ]
          const content = lines.join('\n')

          savePlan({
            id: conversationId!,
            title,
            subject: resolvedSubject,
            grade: resolvedGrade,
            objectives: resolvedObjectives,
            duration: durationMinutes,
            createdAt: t,
            mdUrl: mdUrl || undefined,
            pdfUrl: pdfUrl || undefined,
            mdFilename: mdFilename || undefined,
            pdfFilename: pdfFilename || undefined,
          })

          useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
            content,
            attachment: { type: 'lesson_plan', lessonPlanId: conversationId! },
            steps: assistantSteps,
          })

          updateConversation(conversationId!, {
            title,
            updatedAt: t,
            status: 'completed',
            progress: 100,
          })

          completeTask(taskId)
          setIsGenerating(false)
          return
        }

        if (kind === 'error') {
          done = true
          const msg = toText(payload?.message) || '生成失败'
          setError(msg)
          failTask(taskId, msg)

          if (thinkingStepId) {
            const t = new Date().toISOString()
            patchAssistantStep(thinkingStepId, { status: 'failed', endTime: t, error: msg })
          }

          useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
            content: `出错：${msg}`,
            steps: assistantSteps,
          })

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), status: 'active' })
          setIsGenerating(false)
          return
        }
      },
      (err) => {
        if (done) return
        done = true
        const msg = err.message || '生成失败'
        setError(msg)
        failTask(taskId, msg)

        if (thinkingStepId) {
          const t = new Date().toISOString()
          patchAssistantStep(thinkingStepId, { status: 'failed', endTime: t, error: msg })
        }

        useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
          content: `出错：${msg}`,
          steps: assistantSteps,
        })
        updateConversation(conversationId!, { updatedAt: new Date().toISOString(), status: 'active' })
        setIsGenerating(false)
      },
      () => {
        if (!done) {
          completeTask(taskId)
          setIsGenerating(false)
        }
      }
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const showSplitPane = isGenerating || subAgentActivities.length > 0

  return (
    <div ref={containerRef} className="h-full flex flex-col relative">
      {/* Messages area (or welcome) */}
      {messages.length === 0 && !showSplitPane ? (
        <WelcomeScreen onExampleClick={(text) => setInput(text)} />
      ) : (
        <div className="flex-1 flex overflow-hidden">
          {/* ── Left column: Main agent (chat + steps) ── */}
          <div
            className="flex flex-col overflow-hidden"
            style={{ width: showSplitPane ? `${leftRatio * 100}%` : '100%' }}
          >
            <div ref={scrollRef} className="flex-1 overflow-auto p-4 pb-32">
              <div className="py-6">
                <AnimatePresence mode="popLayout">
                  {messages.map((m) => (
                    <MessageBubble key={m.id} message={m} />
                  ))}
                </AnimatePresence>

                {isGenerating && messages[messages.length - 1]?.content === '' && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex gap-3 mb-4"
                  >
                    <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                      <Loader2 className="h-3 w-3 animate-spin text-primary" />
                    </div>
                    <div className="text-sm text-muted-foreground pt-0.5">
                      正在生成教案...
                    </div>
                  </motion.div>
                )}

                {error && (
                  <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 mb-4 text-sm text-destructive flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-destructive shrink-0" />
                    {error}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ── Draggable divider ── */}
          {showSplitPane && <DraggableDivider onDrag={handleDrag} />}

          {/* ── Right column: SubAgent panel ── */}
          {showSplitPane && (
            <div
              className="flex flex-col overflow-hidden border-l border-border bg-muted/20"
              style={{ width: `${(1 - leftRatio) * 100}%` }}
            >
              <div className="px-4 py-3 border-b border-border bg-background/50 backdrop-blur-sm">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Layers className="h-4 w-4 text-primary" />
                  SubAgent 工作区
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  逐知识点深入研究，为教案提供素材
                </div>
              </div>
              <SubAgentPanel activities={subAgentActivities} />
            </div>
          )}
        </div>
      )}

      {/* ── Composer ── */}
      <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-background via-background to-transparent pt-10"
        style={showSplitPane ? { width: `${leftRatio * 100}%` } : undefined}
      >
        <div className="max-w-3xl mx-auto">
          <form onSubmit={handleSubmit} className="relative group">
            <div className="relative flex items-end gap-2 p-2 rounded-2xl border bg-background shadow-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 transition-all">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-xl text-muted-foreground hover:text-foreground shrink-0 mb-0.5"
                onClick={handleNewConversation}
                title="新建教案"
              >
                <Plus className="h-5 w-5" />
              </Button>

              <Textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="例如：帮我写一份高中数学高二《函数单调性与导数应用》45分钟教案，偏互动式..."
                className="min-h-[44px] max-h-[200px] w-full resize-none border-0 bg-transparent py-2.5 px-0 focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50"
                disabled={isGenerating}
                rows={1}
                style={{ height: 'auto', overflow: 'hidden' }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement
                  target.style.height = 'auto'
                  target.style.height = `${Math.min(target.scrollHeight, 200)}px`
                }}
              />

              <Button
                type="submit"
                size="icon"
                className={cn(
                  'h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all',
                  input.trim() ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                )}
                disabled={!input.trim() || isGenerating}
              >
                {isGenerating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </form>

          <div className="text-center mt-2 text-[10px] text-muted-foreground/50">
            教案生成基于 AI 模型，仅供参考。
          </div>
        </div>
      </div>
    </div>
  )
}

export default LessonPlansPage
