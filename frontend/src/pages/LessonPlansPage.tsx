import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BookOpenCheck,
  ChevronDown,
  Clock,
  Loader2,
  Plus,
  Send,
  Sparkles,
  Target,
  User,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { BrandMark } from '@/components/shared/BrandMark'
import { useSubjects } from '@/hooks/useSubjects'
import { fetchSSE } from '@/api/client'
import { useConversationStore } from '@/stores/useConversationStore'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn, generateId } from '@/lib/utils'
import type { ConversationItem, Message, Subject, TaskStep } from '@/types'

const grades = [
  '一年级',
  '二年级',
  '三年级',
  '四年级',
  '五年级',
  '六年级',
  '七年级',
  '八年级',
  '九年级',
  '高一',
  '高二',
  '高三',
]

type LessonPlanAgentEvent =
  | { event: 'thinking'; data: { content?: unknown } }
  | { event: 'tool_call'; data: { name?: unknown; arguments?: unknown } }
  | { event: 'content'; data: { content?: unknown; section?: unknown } }
  | { event: 'done'; data: { plan?: unknown } }
  | { event: 'error'; data: { message?: unknown } }
  | { event: string; data?: unknown }

function toText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function toObjectives(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        return toText((item as any).description)
      }
      return ''
    })
    .filter(Boolean)
}

function lessonPlanToMarkdown(plan: unknown, ctx: {
  title: string
  subject: string
  grade: string
  topic: string
  durationMinutes: number
  objectives: string[]
}): string {
  const p = (plan && typeof plan === 'object' ? (plan as any) : {}) as any
  const sections = Array.isArray(p.sections) ? (p.sections as any[]) : []
  const summary = toText(p.summary)
  const rawContent = toText(p.content)

  const lines: string[] = [
    `# ${ctx.title}`,
    '',
    '## 课程信息',
    '',
    `- **学科**：${ctx.subject || 'N/A'}`,
    `- **年级**：${ctx.grade || 'N/A'}`,
    `- **课题**：${ctx.topic || 'N/A'}`,
    `- **课时**：${ctx.durationMinutes} 分钟`,
    '',
    '## 教学目标',
    '',
  ]

  if (ctx.objectives.length === 0) {
    lines.push('- （未填写）')
  } else {
    for (const obj of ctx.objectives) {
      lines.push(`- ${obj}`)
    }
  }

  lines.push('', '## 教学环节', '')

  if (sections.length > 0) {
    for (const sec of sections) {
      const title = toText(sec?.title) || '未命名环节'
      const minutes = typeof sec?.duration_minutes === 'number'
        ? sec.duration_minutes
        : typeof sec?.durationMinutes === 'number'
          ? sec.durationMinutes
          : 0
      lines.push(`### ${title}${minutes ? `（${minutes} 分钟）` : ''}`, '')

      const content = toText(sec?.content)
      if (content) {
        lines.push(content, '')
      }

      const activities = Array.isArray(sec?.activities) ? sec.activities : []
      if (activities.length > 0) {
        lines.push('**活动**：')
        for (const act of activities) {
          const text = toText(act)
          if (text) lines.push(`- ${text}`)
        }
        lines.push('')
      }

      const resources = Array.isArray(sec?.resources) ? sec.resources : []
      if (resources.length > 0) {
        lines.push('**资源**：')
        for (const res of resources) {
          const text = toText(res)
          if (text) lines.push(`- ${text}`)
        }
        lines.push('')
      }
    }
  } else if (rawContent) {
    lines.push(rawContent, '')
  } else {
    lines.push('（生成结果未包含环节内容）', '')
  }

  if (summary) {
    lines.push('## 小结', '', summary, '')
  }

  return lines.join('\n')
}

function stripAll(haystack: string, needle: string): string {
  if (!needle) return haystack
  return haystack.split(needle).join('')
}

function getStageByGrade(grade: string | null): '小学' | '初中' | '高中' | '' {
  if (!grade) return ''
  if (grade.startsWith('高')) return '高中'
  if (grade === '七年级' || grade === '八年级' || grade === '九年级') return '初中'
  // 一到六年级通常对应小学
  if (grade.endsWith('年级')) return '小学'
  return ''
}

function extractGradeFromText(text: string): string | null {
  const t = text || ''

  const senior = t.match(/高[一二三]/)?.[0]
  if (senior) return senior

  const junior = t.match(/初[一二三]/)?.[0]
  if (junior === '初一') return '七年级'
  if (junior === '初二') return '八年级'
  if (junior === '初三') return '九年级'

  for (const g of grades) {
    if (t.includes(g)) return g
  }
  return null
}

function extractDurationMinutesFromText(text: string): number | null {
  const t = text || ''
  const m = t.match(/(\d{1,3})\s*(分钟|min)/i)
  if (!m) return null
  const n = Number(m[1])
  if (!Number.isFinite(n)) return null
  if (n < 15 || n > 180) return null
  return n
}

function extractSubjectFromText(
  text: string,
  subjects: Subject[] | undefined,
  grade: string | null
): string | null {
  const list = subjects ?? []
  const t = text || ''

  // 1) Exact/contains match against subject names
  const direct = list
    .map((s) => s?.name)
    .filter((name): name is string => typeof name === 'string' && !!name)
    .filter((name) => t.includes(name))
    .sort((a, b) => b.length - a.length)[0]
  if (direct) return direct

  // 2) Alias match (e.g. "数学" -> "高中数学/初中数学/小学数学")
  const stage = getStageByGrade(grade)
  const stageOrder = stage
    ? [stage, '高中', '初中', '小学']
    : ['高中', '初中', '小学']

  const aliasKeys = [
    '语文',
    '数学',
    '英语',
    '物理',
    '化学',
    '生物',
    '政治',
    '历史',
    '地理',
    '道德与法治',
    '科学',
  ]

  const alias = aliasKeys.find((k) => t.includes(k))
  if (!alias) return null

  const candidates = stageOrder.map((s) => `${s}${alias}`)
  for (const c of candidates) {
    if (list.some((x) => x?.name === c)) return c
  }

  // last fallback: any subject that contains alias
  const fuzzy = list
    .map((s) => s?.name)
    .filter((name): name is string => typeof name === 'string')
    .find((name) => name.includes(alias))
  return fuzzy ?? null
}

function extractTopicFromText(
  text: string,
  subject: string | null,
  grade: string | null
): string {
  const raw = (text || '').trim()
  if (!raw) return ''

  // 《...》 or "..." is often used as topic/title
  const book = raw.match(/《([^》]{2,80})》/)?.[1]?.trim()
  if (book) return book

  const byKey = raw.match(/(?:课题|主题|标题|topic)\s*[:：]\s*(.+)/i)?.[1]
  if (byKey) return byKey.split('\n')[0].trim()

  // Heuristic: strip subject/grade/duration and common filler words
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

function LessonPlanAttachment({ lessonPlanId }: { lessonPlanId: string }) {
  const plan = useLessonPlanStore((state) => state.getPlan(lessonPlanId))

  if (!plan) return null

  return (
    <div className="mt-3 rounded-xl border border-border/80 bg-card/50 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium truncate">{plan.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary">{plan.subject}</Badge>
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {plan.duration} 分钟
            </span>
            {plan.objectives.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <Target className="h-3 w-3" />
                {plan.objectives.length} 个目标
              </span>
            )}
          </div>
        </div>
        <Button asChild size="sm">
          <Link to={`/lesson-plans/${plan.id}`}>查看</Link>
        </Button>
      </div>
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const [showSteps, setShowSteps] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn('flex gap-3 mb-4', isUser ? 'flex-row-reverse' : 'flex-row')}
    >
      <div
        className={cn(
          'h-8 w-8 rounded-full flex items-center justify-center shrink-0',
          isUser ? 'bg-primary text-primary-foreground' : 'bg-foreground text-background'
        )}
      >
        {isUser ? (
          <User className="h-4 w-4" strokeWidth={1.8} />
        ) : (
          <Sparkles className="h-4 w-4" strokeWidth={1.8} />
        )}
      </div>

      <div
        className={cn(
          'max-w-[75%] rounded-2xl px-4 py-3',
          isUser ? 'bg-primary text-primary-foreground' : 'bg-muted'
        )}
      >
        <div className="text-sm whitespace-pre-wrap">{message.content}</div>

        {message.attachment?.type === 'lesson_plan' && (
          <LessonPlanAttachment lessonPlanId={message.attachment.lessonPlanId} />
        )}

        {message.steps && message.steps.length > 0 && (
          <div className="mt-2 pt-2 border-t border-border/50">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-xs px-2"
              onClick={() => setShowSteps(!showSteps)}
            >
              <Sparkles className="h-3 w-3 mr-1" />
              {showSteps ? '隐藏' : '查看'} {message.steps.length} 个执行步骤
            </Button>

            <AnimatePresence>
              {showSteps && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="mt-2 overflow-hidden"
                >
                  <TaskTimeline steps={message.steps} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
    </motion.div>
  )
}

function WelcomeScreen() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
      <BrandMark size={64} className="mb-6" />
      <h2 className="text-2xl font-bold mb-2">教案生成（ChatGPT 对话框 + Manus 时间线）</h2>
      <p className="text-muted-foreground max-w-md mb-8">
        直接像 ChatGPT 一样输入你的需求（建议包含学科/年级/课题/课时），右侧与消息内可查看 Manus 式执行时间线。
      </p>

      <div className="grid grid-cols-2 gap-3 max-w-xl w-full">
        {[
          { title: '函数与导数', desc: '高二数学：函数单调性与导数应用' },
          { title: '力学实验', desc: '高一物理：验证牛顿第二定律' },
          { title: '文言文阅读', desc: '高一语文：文言文断句与翻译' },
          { title: '化学反应速率', desc: '高二化学：影响反应速率的因素' },
        ].map((item) => (
          <div
            key={item.title}
            className={cn(
              'text-left p-4 rounded-xl border border-border/80',
              'bg-card/50 shadow-sm'
            )}
          >
            <div className="flex items-center gap-2 mb-2">
              <div className="h-8 w-8 rounded-lg bg-muted/60 flex items-center justify-center ring-1 ring-border/60">
                <BookOpenCheck className="h-4 w-4 text-foreground/80" strokeWidth={1.8} />
              </div>
              <div className="font-medium text-sm">{item.title}</div>
            </div>
            <div className="text-sm text-muted-foreground leading-5">
              {item.desc}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function LessonPlansPage() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const [input, setInput] = useState('')

  // Optional structured context (used when prompt doesn't include it)
  const [subject, setSubject] = useState('')
  const [grade, setGrade] = useState('')
  const [duration, setDuration] = useState(45)
  const [objectives, setObjectives] = useState('')
  const [additional, setAdditional] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)

  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const prompt = input.trim()
    if (!prompt || isGenerating) return

    const now = new Date().toISOString()

    // Ensure a lesson-plan conversation is selected
    let conversationId = activeConversationId
    if (!conversationId) {
      const inferredGrade = extractGradeFromText(prompt) ?? (grade || null)
      const inferredSubject =
        extractSubjectFromText(prompt, subjects, inferredGrade) ?? (subject || null)
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

    const existingPlan = useLessonPlanStore.getState().getPlan(conversationId)

    const inferredGrade = extractGradeFromText(prompt)
    const resolvedGrade = (
      inferredGrade ??
      (showAdvanced ? grade : existingPlan?.grade ?? grade) ??
      ''
    ).trim()

    const inferredSubject = extractSubjectFromText(
      prompt,
      subjects,
      resolvedGrade || existingPlan?.grade || null
    )
    const resolvedSubject = (
      inferredSubject ??
      (showAdvanced ? subject : existingPlan?.subject ?? subject) ??
      ''
    ).trim()

    const inferredTopic = extractTopicFromText(
      prompt,
      resolvedSubject || null,
      resolvedGrade || null
    )
    const resolvedTopic = (inferredTopic || existingPlan?.title || '').trim()

    const resolvedDuration =
      extractDurationMinutesFromText(prompt) ??
      (showAdvanced ? duration : existingPlan?.duration ?? duration) ??
      45

    const resolvedObjectives = showAdvanced
      ? objectives
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean)
      : existingPlan?.objectives ?? []

    const resolvedAdditional = [
      showAdvanced ? additional.trim() : '',
      prompt,
    ]
      .filter(Boolean)
      .join('\n\n')

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
          `“高中数学 高二 《函数单调性与导数应用》 45分钟 教案（互动式/含分层练习）”。\n\n` +
          `也可以展开下方“高级选项”手动选择。`,
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

    let runningStepId: string | null = null
    let done = false
    let hasContent = false

    let assistantSteps: TaskStep[] = []
    let assistantText = ''
    let pendingText = ''
    let flushTimer: number | null = null

    const flushAssistant = () => {
      if (!pendingText) return
      assistantText += pendingText
      pendingText = ''
      useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
        content: assistantText,
      })
    }

    const syncSteps = () => {
      useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
        steps: assistantSteps,
      })
    }

    const updateAssistantStep = (stepId: string, patch: Partial<TaskStep>) => {
      assistantSteps = assistantSteps.map((s) => (s.id === stepId ? { ...s, ...patch } : s))
      syncSteps()
    }

    const startRunningStep = (title: string, extra?: Partial<TaskStep>) => {
      const t = new Date().toISOString()
      if (runningStepId) {
        updateStep(taskId, runningStepId, { status: 'completed', endTime: t })
        updateAssistantStep(runningStepId, { status: 'completed', endTime: t })
      }

      const step: TaskStep = {
        id: generateId(),
        title,
        status: 'running',
        startTime: t,
        ...extra,
      }
      runningStepId = step.id
      addStep(taskId, step)
      assistantSteps = [...assistantSteps, step]
      syncSteps()
    }

    startRunningStep('接收请求并开始生成…')

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
          startRunningStep(text)
          updateConversation(conversationId, { updatedAt: new Date().toISOString(), progress: 20 })
          return
        }

        if (kind === 'tool_call') {
          const name = toText(payload?.name) || 'tool'
          startRunningStep(`调用工具：${name}`, { toolName: name, input: payload?.arguments })
          updateConversation(conversationId, { updatedAt: new Date().toISOString(), progress: 40 })
          return
        }

        if (kind === 'content') {
          if (!hasContent) {
            hasContent = true
            startRunningStep('生成教案正文…')
          }
          const chunk = toText(payload?.content)
          if (chunk) {
            pendingText += chunk
            if (flushTimer == null) {
              flushTimer = window.setTimeout(() => {
                flushTimer = null
                flushAssistant()
              }, 60)
            }
          }
          updateConversation(conversationId, { updatedAt: new Date().toISOString(), progress: 70 })
          return
        }

        if (kind === 'done') {
          done = true
          if (flushTimer != null) {
            window.clearTimeout(flushTimer)
            flushTimer = null
          }
          flushAssistant()

          const t = new Date().toISOString()
          if (runningStepId) {
            updateStep(taskId, runningStepId, { status: 'completed', endTime: t })
            updateAssistantStep(runningStepId, { status: 'completed', endTime: t })
          }

          const planRaw = payload?.plan
          const title = toText((planRaw as any)?.title) || resolvedTopic || '教案'
          const durationMinutes =
            typeof (planRaw as any)?.duration_minutes === 'number'
              ? (planRaw as any).duration_minutes
              : resolvedDuration
          const planObjectives = toObjectives((planRaw as any)?.objectives)

          const md = lessonPlanToMarkdown(planRaw, {
            title,
            subject: resolvedSubject,
            grade: resolvedGrade,
            topic: resolvedTopic,
            durationMinutes,
            objectives: planObjectives.length > 0 ? planObjectives : resolvedObjectives,
          })

          savePlan({
            id: conversationId,
            title,
            subject: resolvedSubject,
            grade: resolvedGrade,
            objectives: planObjectives.length > 0 ? planObjectives : resolvedObjectives,
            content: md,
            duration: durationMinutes,
            createdAt: t,
          })

          useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
            content: md,
            attachment: { type: 'lesson_plan', lessonPlanId: conversationId },
            steps: assistantSteps,
          })

          updateConversation(conversationId, {
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

          useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
            content: `出错：${msg}`,
            steps: assistantSteps,
          })

          updateConversation(conversationId, { updatedAt: new Date().toISOString(), status: 'active' })
          setIsGenerating(false)
        }
      },
      (err) => {
        if (done) return
        const msg = err.message || '生成失败'
        setError(msg)
        failTask(taskId, msg)
        useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
          content: `出错：${msg}`,
          steps: assistantSteps,
        })
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

  return (
    <div className="h-full flex flex-col">
      {/* Top bar */}
      <div className="border-b border-border p-3 glass flex items-center justify-between">
        <div className="text-sm font-medium text-muted-foreground">
          教案生成 · Manus 时间轴
        </div>
        <Button variant="outline" size="sm" onClick={handleNewConversation} className="gap-2">
          <Plus className="h-4 w-4" />
          新建教案对话
        </Button>
      </div>

      {/* Messages */}
      {messages.length === 0 ? (
        <WelcomeScreen />
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-auto p-4">
          <div className="max-w-3xl mx-auto">
            <AnimatePresence mode="popLayout">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </AnimatePresence>

            {error && (
              <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 mb-4">
                <p className="text-sm text-destructive">{error}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Composer */}
      <div className="border-t border-border p-4 glass">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
          <div className="relative">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="例如：帮我写一份高中数学高二《函数单调性与导数应用》45分钟教案，偏互动式，包含分层练习与评价方式。（Shift+Enter 换行）"
              className="min-h-[60px] max-h-[200px] pr-12 resize-none"
              disabled={isGenerating}
            />
            <Button
              type="submit"
              size="icon"
              className="absolute right-2 bottom-2"
              disabled={!input.trim() || isGenerating}
            >
              {isGenerating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </div>

          <div className="mt-2 flex items-center justify-between gap-3">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="gap-1 text-muted-foreground hover:text-foreground"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              <ChevronDown className={cn('h-4 w-4 transition-transform', showAdvanced && 'rotate-180')} />
              高级选项
            </Button>

            {isGenerating && (
              <Badge variant="secondary" className="gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                生成中…
              </Badge>
            )}
          </div>

          <AnimatePresence initial={false}>
            {showAdvanced && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <label className="text-xs text-muted-foreground">学科（可选）</label>
                    <select
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      className="w-full h-10 mt-1 rounded-md border border-input bg-background px-3"
                      disabled={isGenerating}
                    >
                      <option value="">自动识别</option>
                      {subjects?.map((s) => (
                        <option key={s.id} value={s.name}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-muted-foreground">年级（可选）</label>
                    <select
                      value={grade}
                      onChange={(e) => setGrade(e.target.value)}
                      className="w-full h-10 mt-1 rounded-md border border-input bg-background px-3"
                      disabled={isGenerating}
                    >
                      <option value="">自动识别</option>
                      {grades.map((g) => (
                        <option key={g} value={g}>
                          {g}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-muted-foreground">课时（分钟，可选）</label>
                    <Input
                      type="number"
                      min={15}
                      max={180}
                      value={duration}
                      onChange={(e) => setDuration(parseInt(e.target.value) || 45)}
                      className="mt-1"
                      disabled={isGenerating}
                    />
                  </div>
                </div>

                <div className="mt-3">
                  <label className="text-xs text-muted-foreground">
                    教学目标（每行一个，可选）
                  </label>
                  <Textarea
                    value={objectives}
                    onChange={(e) => setObjectives(e.target.value)}
                    placeholder="例如：\n1. 理解概念\n2. 掌握方法\n3. 形成能力"
                    rows={3}
                    className="mt-1"
                    disabled={isGenerating}
                  />
                </div>

                <div className="mt-3">
                  <label className="text-xs text-muted-foreground">补充要求（可选）</label>
                  <Textarea
                    value={additional}
                    onChange={(e) => setAdditional(e.target.value)}
                    placeholder="例如：更偏互动式教学；包含分层练习与评价方式"
                    rows={3}
                    className="mt-1"
                    disabled={isGenerating}
                  />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </form>
      </div>
    </div>
  )
}
