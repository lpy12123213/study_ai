import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BookOpenCheck,
  Clock,
  Loader2,
  Plus,
  Send,
  Sparkles,
  ArrowRight,
  ChevronDown,
  ChevronUp
} from 'lucide-react'
import { Button } from '@/components/ui/button'
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

// ... (keep helper functions: grades, toText, toObjectives, lessonPlanToMarkdown, stripAll, getStageByGrade, extractGradeFromText, extractDurationMinutesFromText, extractSubjectFromText, extractTopicFromText, toConversationTitle)

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
      className="flex flex-col gap-2 mb-8 max-w-3xl w-full"
    >
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
        <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center">
          <BrandMark size={12} />
        </div>
        <span>学习助手</span>
      </div>
      
      <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-7">
        <div className="whitespace-pre-wrap">{message.content}</div>
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

export default function LessonPlansPage() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const [input, setInput] = useState('')

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

    const existingPlan = useLessonPlanStore.getState().getPlan(conversationId)

    const inferredGrade = extractGradeFromText(prompt)
    const resolvedGrade = (inferredGrade ?? existingPlan?.grade ?? '').trim()

    const inferredSubject = extractSubjectFromText(
      prompt,
      subjects,
      resolvedGrade || existingPlan?.grade || null
    )
    const resolvedSubject = (inferredSubject ?? existingPlan?.subject ?? '').trim()

    const inferredTopic = extractTopicFromText(
      prompt,
      resolvedSubject || null,
      resolvedGrade || null
    )
    const resolvedTopic = (inferredTopic || existingPlan?.title || '').trim()

    const resolvedDuration =
      extractDurationMinutesFromText(prompt) ?? existingPlan?.duration ?? 45

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
    <div className="h-full flex flex-col relative">
      {/* Messages */}
      {messages.length === 0 ? (
        <WelcomeScreen onExampleClick={(text) => setInput(text)} />
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-auto p-4 pb-32">
          <div className="max-w-3xl mx-auto py-6">
            <AnimatePresence mode="popLayout">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </AnimatePresence>

            {isGenerating && messages[messages.length - 1]?.content === '' && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex gap-3 mb-4 max-w-3xl"
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
      )}

      {/* Composer */}
      <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-background via-background to-transparent pt-10">
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
                  const target = e.target as HTMLTextAreaElement;
                  target.style.height = 'auto';
                  target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
                }}
              />
              
              <Button
                type="submit"
                size="icon"
                className={cn(
                  "h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all",
                  input.trim() ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
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
