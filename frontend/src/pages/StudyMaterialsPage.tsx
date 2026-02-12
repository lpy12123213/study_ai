import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { BookOpen, GripVertical, Layers, Loader2, Plus, Send, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { BrandMark } from '@/components/shared/BrandMark'
import { fetchSSERequest } from '@/api/client'
import { useConversationStore } from '@/stores/useConversationStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn, generateId } from '@/lib/utils'
import type { ConversationItem, Message, TaskStep } from '@/types'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'

type StudyMaterialsAgentEvent = {
  event: string
  data?: any
  seq?: unknown
  task_id?: unknown
}

function toText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function toConversationTitle(text: string): string {
  const t = (text || '').trim()
  if (!t) return '新自学资料'
  return t.length > 18 ? `${t.slice(0, 18)}…` : t
}

type TriState = 'default' | 'on' | 'off'

function normalizeKnowledgePoints(points: unknown): string[] {
  if (!Array.isArray(points)) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of points) {
    const text = typeof item === 'string' ? item.trim() : ''
    if (!text) continue
    if (seen.has(text)) continue
    seen.add(text)
    out.push(text)
    if (out.length >= 15) break
  }
  return out
}

function extractStepKnowledgePoints(step: TaskStep): string[] {
  if (step.input && typeof step.input === 'object') {
    const input = step.input as Record<string, unknown>
    const fromInput = normalizeKnowledgePoints(input.knowledge_points)
    if (fromInput.length > 0) return fromInput
  }

  const title = (step.title || '').trim()
  const m = title.match(/当前知识点[：:]\s*([^\r\n]+)/)
  if (m && m[1]) {
    return normalizeKnowledgePoints([m[1].trim()])
  }
  return []
}

// ── SubAgent types and components ───────────────────────────────────

interface SubAgentActivity {
  knowledgePoint: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  steps: TaskStep[]
}

function SubAgentPanel({
  activities,
  activeTab,
  onTabChange,
}: {
  activities: SubAgentActivity[]
  activeTab: string | null
  onTabChange: (kp: string) => void
}) {
  if (!activities.length) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-muted-foreground text-sm">
        等待知识点拆分...
      </div>
    )
  }

  const selectedKP = activeTab || activities[0]?.knowledgePoint || null
  const selectedActivity = activities.find((a) => a.knowledgePoint === selectedKP)

  const statusIcon = (status: SubAgentActivity['status']) => {
    if (status === 'pending') return <div className="h-2 w-2 rounded-full bg-muted-foreground/30" />
    if (status === 'running') return <Loader2 className="h-3 w-3 animate-spin text-primary" />
    if (status === 'failed') return <div className="h-2 w-2 rounded-full bg-destructive" />
    return <div className="h-2 w-2 rounded-full bg-green-500" />
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 p-2 border-b border-border bg-muted/30 shrink-0">
        {activities.map((activity) => {
          const isActive = activity.knowledgePoint === selectedKP
          return (
            <button
              key={activity.knowledgePoint}
              onClick={() => onTabChange(activity.knowledgePoint)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors',
                isActive
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
              )}
            >
              {statusIcon(activity.status)}
              <span>{activity.knowledgePoint}</span>
            </button>
          )
        })}
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-auto p-4">
        {selectedActivity ? (
          <div>
            <div className="flex items-center gap-2 mb-4">
              {statusIcon(selectedActivity.status)}
              <span className="text-sm font-medium">{selectedActivity.knowledgePoint}</span>
              <Badge
                variant={
                  selectedActivity.status === 'running'
                    ? 'default'
                    : selectedActivity.status === 'completed'
                      ? 'secondary'
                      : selectedActivity.status === 'failed'
                        ? 'destructive'
                        : 'outline'
                }
                className="text-xs"
              >
                {selectedActivity.status === 'pending'
                  ? '待处理'
                  : selectedActivity.status === 'running'
                    ? '进行中'
                    : selectedActivity.status === 'failed'
                      ? '失败'
                      : '已完成'}
              </Badge>
            </div>

            {selectedActivity.steps.length > 0 ? (
              <TaskTimeline steps={selectedActivity.steps} />
            ) : (
              <div className="text-sm text-muted-foreground">
                {selectedActivity.status === 'pending'
                  ? '等待开始...'
                  : '暂无步骤记录'}
              </div>
            )}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">选择一个知识点查看详情</div>
        )}
      </div>
    </div>
  )
}

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

function MessageBubble({
  message,
}: {
  message: Message
}) {
  const isUser = message.role === 'user'

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
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
        >
          {message.content}
        </ReactMarkdown>
      </div>

      {message.steps && message.steps.length > 0 && (
        (() => {
          const allSteps = message.steps || []

          // Only show global steps (main agent), subagent steps are shown in the right panel
          const globalSteps: TaskStep[] = []

          for (const step of allSteps) {
            const kps = extractStepKnowledgePoints(step)
            // Steps without a specific knowledge point are global (main agent)
            if (kps.length !== 1) {
              globalSteps.push(step)
            }
          }

          if (globalSteps.length === 0) return null

          return (
            <div className="mt-3 overflow-hidden rounded-lg border border-border bg-card">
              <div className="px-4 py-2 text-xs text-muted-foreground flex items-center justify-between">
                <span>主流程步骤</span>
                <span className="tabular-nums">{globalSteps.length} 步</span>
              </div>
              <div className="p-4 bg-muted/30">
                <TaskTimeline steps={globalSteps} />
              </div>
            </div>
          )
        })()
      )}
    </motion.div>
  )
}

function WelcomeScreen({ onExampleClick }: { onExampleClick: (text: string) => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 animate-in fade-in duration-500">
      <div className="mb-10 flex flex-col items-center text-center space-y-6">
        <div className="h-20 w-20 rounded-3xl bg-gradient-to-br from-primary/5 to-primary/10 flex items-center justify-center ring-1 ring-border/50 shadow-sm">
           <BookOpen className="h-10 w-10 text-primary" strokeWidth={1.5} />
        </div>
        <h2 className="text-2xl font-semibold tracking-tight">自学资料生成</h2>
        <p className="text-muted-foreground max-w-md">
           输入你想学的知识点（例如“函数单调性”），我将为你检索题目、生成讲解与例题步骤。
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full">
        {[
          { title: '函数单调性', desc: '高中数学：定义法与典型例题' },
          { title: '二次函数最值', desc: '配方法/判别式/图像理解' },
          { title: '受力分析', desc: '受力图、正交分解、常见陷阱' },
          { title: '化学平衡常数', desc: 'K 的表达式、比较与计算' },
        ].map((item) => (
          <button
            key={item.title}
            onClick={() => onExampleClick(item.desc)}
            className="group relative flex flex-col items-start p-4 h-auto text-left rounded-xl border bg-card hover:bg-accent/50 hover:border-accent transition-all duration-200 hover:-translate-y-0.5 shadow-sm hover:shadow-md"
          >
            <div className="mb-3 rounded-lg bg-muted p-2 group-hover:bg-background transition-colors">
              <BookOpen className="h-4 w-4 text-muted-foreground group-hover:text-foreground" />
            </div>
            <div className="font-medium text-sm mb-1">{item.title}</div>
            <div className="text-xs text-muted-foreground line-clamp-2">{item.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

export default function StudyMaterialsPage() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const streamAbortRef = useRef<AbortController | null>(null)
  const streamKeyRef = useRef<string | null>(null)

  const [input, setInput] = useState('')
  const [isGeneratingLocal, setIsGeneratingLocal] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Split pane: left panel width ratio (0.25 to 0.75)
  const [leftRatio, setLeftRatio] = useState(0.38)

  // SubAgent activities for the right panel
  const [subAgentActivities, setSubAgentActivities] = useState<SubAgentActivity[]>([])

  // Active tab in SubAgent panel
  const [activeSubAgentTab, setActiveSubAgentTab] = useState<string | null>(null)

  // Advanced options (optional; when unset, backend uses `.env` defaults)
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [subject, setSubject] = useState('')
  const [preset, setPreset] = useState<'quick' | 'standard' | 'deep' | 'research' | ''>('')
  const [requirements, setRequirements] = useState('')
  const [withQuestions, setWithQuestions] = useState<TriState>('default')
  const [withDiagrams, setWithDiagrams] = useState<TriState>('default')
  const [enableExtraTools, setEnableExtraTools] = useState<TriState>('default')
  const [maxPoints, setMaxPoints] = useState<string>('')

  const conversations = useConversationStore((state) => state.conversations)
  const currentConversationId = useConversationStore((state) => state.currentConversationId)
  const addConversation = useConversationStore((state) => state.addConversation)
  const setCurrentConversation = useConversationStore((state) => state.setCurrentConversation)
  const updateConversation = useConversationStore((state) => state.updateConversation)
  const setMessages = useConversationStore((state) => state.setMessages)
  const addMessage = useConversationStore((state) => state.addMessage)

  const activeConversationId = useMemo(() => {
    if (!currentConversationId) return null
    const current = conversations.find((c) => c.id === currentConversationId)
    // Reuse existing conversation type `lesson_plan` as “自学资料”
    return current?.type === 'lesson_plan' ? currentConversationId : null
  }, [conversations, currentConversationId])

  const activeConversation = useMemo(() => {
    if (!activeConversationId) return null
    return conversations.find((c) => c.id === activeConversationId) ?? null
  }, [conversations, activeConversationId])

  const activeStream = activeConversation?.activeStream
  const hasResumableStream = Boolean(activeStream?.taskId)
  const isGenerating = isGeneratingLocal

  const messages = useConversationStore((state) =>
    state.getMessages(activeConversationId ?? '')
  )

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages.length])

  const abortActiveStream = useCallback(() => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort()
      streamAbortRef.current = null
    }
    streamKeyRef.current = null
    setIsGeneratingLocal(false)
  }, [])

  const handleDrag = useCallback((deltaX: number) => {
    if (!containerRef.current) return
    const totalWidth = containerRef.current.offsetWidth
    if (totalWidth <= 0) return
    setLeftRatio((prev) => {
      const next = prev + deltaX / totalWidth
      return Math.max(0.2, Math.min(0.65, next))
    })
  }, [])

  const runStudyMaterialsStream = useCallback((opts: {
    conversationId: string
    assistantMessageId: string
    request: { url: string; method: 'GET' | 'POST'; body?: unknown }
    localTaskId?: string
    initialTaskId?: string
    initialSeq?: number
    streamKey?: string
  }) => {
    const { conversationId, assistantMessageId, request, localTaskId } = opts
    const controller = new AbortController()
    const initialSeq = typeof opts.initialSeq === 'number' ? opts.initialSeq : 0

    // Cancel any existing stream before starting a new one.
    abortActiveStream()
    streamAbortRef.current = controller
    streamKeyRef.current = opts.streamKey || null

    let serverTaskId: string | null = (opts.initialTaskId || '').trim() || null
    let lastSeq = initialSeq

    const existing = useConversationStore
      .getState()
      .getMessages(conversationId)
      .find((m) => m.id === assistantMessageId)

    let assistantSteps: TaskStep[] = Array.isArray(existing?.steps) ? (existing?.steps as TaskStep[]) : []
    let assistantText = typeof existing?.content === 'string' ? existing!.content : ''
    let pendingText = ''
    let flushTimer: number | null = null
    let done = false

    const flushAssistant = () => {
      if (!pendingText) return
      assistantText += pendingText
      pendingText = ''
      useConversationStore.getState().updateMessage(conversationId, assistantMessageId, { content: assistantText })
    }

    const syncSteps = () => {
      useConversationStore.getState().updateMessage(conversationId, assistantMessageId, { steps: assistantSteps })
    }

    const upsertAssistantStep = (step: TaskStep) => {
      const existingStep = assistantSteps.find((s) => s.id === step.id)
      if (!existingStep) {
        assistantSteps = [...assistantSteps, step]
        syncSteps()
        return
      }
      assistantSteps = assistantSteps.map((s) => (s.id === step.id ? { ...s, ...step } : s))
      syncSteps()
    }

    const patchAssistantStep = (stepId: string, patch: Partial<TaskStep>) => {
      const exists = assistantSteps.some((s) => s.id === stepId)
      if (!exists) {
        assistantSteps = [
          ...assistantSteps,
          {
            id: stepId,
            title: patch.title || patch.toolName || '步骤',
            status: patch.status || 'running',
            startTime: patch.startTime,
            endTime: patch.endTime,
            toolName: patch.toolName,
            input: patch.input,
            output: patch.output,
            error: patch.error,
          },
        ]
        syncSteps()
        return
      }
      assistantSteps = assistantSteps.map((s) => (s.id === stepId ? { ...s, ...patch } : s))
      syncSteps()
    }

    const recordSeq = (seq: number) => {
      if (!Number.isFinite(seq) || seq <= lastSeq) return
      lastSeq = seq
      if (!serverTaskId) return

      useConversationStore.getState().updateConversation(conversationId, {
        activeStream: {
          taskType: 'study_materials',
          taskId: serverTaskId,
          assistantMessageId,
          lastSeq,
        },
        resumable: true,
      })
    }

    setIsGeneratingLocal(true)
    setError(null)

    void fetchSSERequest(
      request.url,
      {
        method: request.method,
        body: request.body,
        signal: controller.signal,
      },
      (data) => {
        // Ignore events from a previous stream.
        if (streamAbortRef.current !== controller) return

        const evt = data as StudyMaterialsAgentEvent
        const kind = typeof evt?.event === 'string' ? evt.event : ''
        const payload = evt?.data
        const seqRaw = evt?.seq
        const seq = typeof seqRaw === 'number' ? seqRaw : typeof seqRaw === 'string' ? Number(seqRaw) : NaN
        if (Number.isFinite(seq)) recordSeq(seq as number)

        if (kind === 'task_started') {
          const taskId = toText(payload?.task_id) || toText(evt?.task_id)
          if (taskId) {
            serverTaskId = taskId
            streamKeyRef.current = `${conversationId}:${taskId}`
            useConversationStore.getState().updateConversation(conversationId, {
              activeStream: {
                taskType: 'study_materials',
                taskId,
                assistantMessageId,
                lastSeq: Number.isFinite(seq) ? (seq as number) : 0,
              },
              resumable: true,
              status: 'active',
              updatedAt: new Date().toISOString(),
            })
          }
          return
        }

        if (kind === 'ping') {
          // Keep-alive; nothing to do.
          return
        }

        if (kind === 'warning') {
          const msg = toText(payload?.message)
          if (msg) setError(msg)
          return
        }

        if (kind === 'thinking') {
          const text = toText(payload?.content) || '思考中…'
          const t = new Date().toISOString()
          upsertAssistantStep({
            id: generateId(),
            title: text,
            status: 'completed',
            startTime: t,
            endTime: t,
          })
          return
        }

        if (kind === 'tool_call') {
          const name = toText(payload?.name) || 'tool'
          const stepId = toText(payload?.step_id) || generateId()
          const stepTitle = toText(payload?.title)
          const t = new Date().toISOString()

          const step: TaskStep = {
            id: stepId,
            title: stepTitle || `调用工具：${name}`,
            status: 'running',
            startTime: t,
            toolName: name,
            input: payload?.arguments,
          }

          upsertAssistantStep(step)
          if (localTaskId) {
            useTaskStore.getState().addStep(localTaskId, step)
          }

          const stepKps = normalizeKnowledgePoints((payload as any)?.arguments?.knowledge_points)
          if (stepKps.length === 1) {
            const kp = stepKps[0]
            setSubAgentActivities((prev) => {
              const exists = prev.some((a) => a.knowledgePoint === kp)
              const base = exists
                ? prev
                : [...prev, { knowledgePoint: kp, status: 'pending' as const, steps: [] }]
              return base.map((a) =>
                a.knowledgePoint === kp
                  ? { ...a, steps: [...a.steps, step] }
                  : a
              )
            })
          }

          useConversationStore.getState().updateConversation(conversationId, {
            updatedAt: new Date().toISOString(),
            progress: 40,
          })
          return
        }

        if (kind === 'tool_result') {
          const toolName = toText(payload?.name) || ''
          const stepId = toText(payload?.step_id)
          if (!stepId) return

          const success = (payload as any)?.success === true
          const out = (payload as any)?.output
          const err = toText(payload?.error)
          const t = new Date().toISOString()

          patchAssistantStep(stepId, {
            status: success ? 'completed' : 'failed',
            endTime: t,
            output: out,
            error: err || undefined,
            toolName: toolName || undefined,
          })

          if (localTaskId) {
            useTaskStore.getState().updateStep(localTaskId, stepId, {
              status: success ? 'completed' : 'failed',
              endTime: t,
              output: out,
              error: err || undefined,
            })
          }

          const updated = assistantSteps.find((s) => s.id === stepId)
          const kps = updated ? extractStepKnowledgePoints(updated) : []
          if (kps.length === 1) {
            const kp = kps[0]
            setSubAgentActivities((prev) => {
              const exists = prev.some((a) => a.knowledgePoint === kp)
              const base = exists
                ? prev
                : [...prev, { knowledgePoint: kp, status: 'pending' as const, steps: [] }]

              return base.map((a) => {
                if (a.knowledgePoint !== kp) return a

                const hasStep = a.steps.some((s) => s.id === stepId)
                const nextSteps = hasStep
                  ? a.steps.map((s) =>
                      s.id === stepId
                        ? {
                            ...s,
                            status: success ? ('completed' as const) : ('failed' as const),
                            endTime: t,
                            output: out,
                            error: err || undefined,
                          }
                        : s
                    )
                  : updated
                    ? [...a.steps, updated]
                    : a.steps

                return {
                  ...a,
                  status: success ? a.status : ('failed' as const),
                  steps: nextSteps,
                }
              })
            })
          }

          // Initialize subAgentActivities when split_knowledge_points returns
          if (toolName === 'split_knowledge_points' && out && typeof out === 'object') {
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
          return
        }

        if (kind === 'subagent_start') {
          const kp = toText(payload?.knowledge_point)
          if (kp) {
            setSubAgentActivities((prev) => {
              const exists = prev.some((a) => a.knowledgePoint === kp)
              const base = exists
                ? prev
                : [...prev, { knowledgePoint: kp, status: 'pending' as const, steps: [] }]
              return base.map((a) =>
                a.knowledgePoint === kp ? { ...a, status: 'running' as const } : a
              )
            })
            setActiveSubAgentTab((prev) => prev || kp)
          }
          return
        }

        if (kind === 'subagent_end') {
          const kp = toText(payload?.knowledge_point)
          if (kp) {
            setSubAgentActivities((prev) =>
              prev.map((a) =>
                a.knowledgePoint === kp
                  ? {
                      ...a,
                      status: a.status === 'failed' ? ('failed' as const) : ('completed' as const),
                      steps: a.steps.map((s) =>
                        s.status === 'running'
                          ? { ...s, status: 'completed' as const, endTime: new Date().toISOString() }
                          : s
                      ),
                    }
                  : a
              )
            )
          }
          return
        }

        if (kind === 'content') {
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
          useConversationStore.getState().updateConversation(conversationId, {
            updatedAt: new Date().toISOString(),
            progress: 70,
          })
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
          const md = toText(payload?.material?.markdown)
          if (md) {
            assistantText = md
            useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
              content: md,
              steps: assistantSteps,
            })
          }

          useConversationStore.getState().updateConversation(conversationId, {
            updatedAt: t,
            status: 'completed',
            progress: 100,
            activeStream: undefined,
            resumable: false,
          })

          if (localTaskId) {
            useTaskStore.getState().completeTask(localTaskId)
          }

          setIsGeneratingLocal(false)
          return
        }

        if (kind === 'error') {
          done = true
          const msg = toText(payload?.message) || '生成失败'
          setError(msg)

          if (flushTimer != null) {
            window.clearTimeout(flushTimer)
            flushTimer = null
          }
          flushAssistant()

          useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
            content: `出错：${msg}`,
            steps: assistantSteps,
          })

          useConversationStore.getState().updateConversation(conversationId, {
            updatedAt: new Date().toISOString(),
            status: 'active',
            activeStream: undefined,
            resumable: false,
          })

          if (localTaskId) {
            useTaskStore.getState().failTask(localTaskId, msg)
          }

          setIsGeneratingLocal(false)
        }
      },
      (err) => {
        if (streamAbortRef.current !== controller) return
        if (done) return

        const msg = err.message || '生成失败'
        setError(msg)
        if (localTaskId) {
          useTaskStore.getState().failTask(localTaskId, msg)
        }
        useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
          content: `出错：${msg}`,
          steps: assistantSteps,
        })
        // Keep activeStream so the user can refresh/reconnect.
        setIsGeneratingLocal(false)
      },
      () => {
        if (streamAbortRef.current !== controller) return
        if (!done) {
          // Connection closed unexpectedly: keep the task resumable.
          setIsGeneratingLocal(false)
        }
        streamAbortRef.current = null
      }
    )
  }, [abortActiveStream])

  // Resume after refresh: if a conversation has an active stream, reconnect from last seq.
  useEffect(() => {
    if (!activeConversationId) return
    const stream = activeConversation?.activeStream
    if (!stream?.taskId || !stream.assistantMessageId) return

    const key = `${activeConversationId}:${stream.taskId}`
    if (streamKeyRef.current === key) return
    runStudyMaterialsStream({
      conversationId: activeConversationId,
      assistantMessageId: stream.assistantMessageId,
      request: {
        url: `/study-materials/tasks/${encodeURIComponent(stream.taskId)}/stream?after_seq=${Number(stream.lastSeq || 0)}`,
        method: 'GET',
      },
      initialTaskId: stream.taskId,
      initialSeq: Number(stream.lastSeq || 0),
      streamKey: key,
    })
  }, [activeConversationId, activeConversation?.activeStream?.taskId, runStudyMaterialsStream])

  useEffect(() => {
    return () => {
      abortActiveStream()
    }
  }, [abortActiveStream])

  const handleNewConversation = () => {
    abortActiveStream()
    const id = generateId()
    const now = new Date().toISOString()
    const item: ConversationItem = {
      id,
      title: '新自学资料',
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
    setActiveSubAgentTab(null)
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const prompt = input.trim()
    if (!prompt || isGenerating) return

    const now = new Date().toISOString()

    // Ensure a study-materials conversation is selected (reuse lesson_plan type)
    let conversationId = activeConversationId
    if (!conversationId) {
      conversationId = generateId()
      const conversation: ConversationItem = {
        id: conversationId,
        title: toConversationTitle(prompt),
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
      updateConversation(conversationId, {
        title: toConversationTitle(prompt),
        updatedAt: now,
        status: 'active',
        progress: 0,
        activeStream: undefined,
        resumable: false,
      })
    }

    // Starting a new run clears any previous resumable stream state for this conversation.
    useConversationStore.getState().updateConversation(conversationId, {
      activeStream: undefined,
      resumable: false,
    })

    addMessage(conversationId, {
      id: generateId(),
      role: 'user',
      content: prompt,
      createdAt: now,
    })

    setInput('')
    setError(null)
    setSubAgentActivities([])
    setActiveSubAgentTab(null)

    const assistantMessageId = generateId()
    addMessage(conversationId, {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      createdAt: now,
      steps: [],
    })

    const localTaskId = `study-materials-${conversationId}-${Date.now()}`
    useTaskStore.getState().startTask(localTaskId)

    const toOptionalBool = (v: TriState): boolean | undefined => {
      if (v === 'on') return true
      if (v === 'off') return false
      return undefined
    }

    const body: Record<string, unknown> = { query: prompt }
    const subjectValue = subject.trim()
    if (subjectValue) body.subject = subjectValue
    if (preset) body.preset = preset
    const requirementsValue = requirements.trim()
    if (requirementsValue) body.requirements = requirementsValue

    const withQuestionsValue = toOptionalBool(withQuestions)
    if (withQuestionsValue !== undefined) body.with_questions = withQuestionsValue
    const withDiagramsValue = toOptionalBool(withDiagrams)
    if (withDiagramsValue !== undefined) body.with_diagrams = withDiagramsValue
    const enableExtraToolsValue = toOptionalBool(enableExtraTools)
    if (enableExtraToolsValue !== undefined) body.enable_extra_tools = enableExtraToolsValue

    const maxPointsRaw = maxPoints.trim()
    if (maxPointsRaw) {
      const n = Number(maxPointsRaw)
      if (Number.isFinite(n) && n > 0) body.max_points = Math.max(1, Math.min(15, Math.floor(n)))
    }

    runStudyMaterialsStream({
      conversationId,
      assistantMessageId,
      request: {
        url: '/study-materials/generate',
        method: 'POST',
        body,
      },
      localTaskId,
      initialSeq: 0,
      streamKey: `${conversationId}:${assistantMessageId}`,
    })
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
                {hasResumableStream && !isGenerating && activeConversationId && activeStream && (
                  <div className="mt-3 mb-4 rounded-xl border border-border bg-card p-3 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-muted-foreground">
                        检测到未完成的生成任务，可继续接收输出（支持刷新恢复）。
                      </div>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          onClick={() => {
                            runStudyMaterialsStream({
                              conversationId: activeConversationId,
                              assistantMessageId: activeStream.assistantMessageId,
                              request: {
                                url: `/study-materials/tasks/${encodeURIComponent(activeStream.taskId)}/stream?after_seq=${Number(activeStream.lastSeq || 0)}`,
                                method: 'GET',
                              },
                              initialTaskId: activeStream.taskId,
                              initialSeq: Number(activeStream.lastSeq || 0),
                              streamKey: `${activeConversationId}:${activeStream.taskId}`,
                            })
                          }}
                        >
                          继续
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => {
                            abortActiveStream()
                            useConversationStore.getState().updateConversation(activeConversationId, {
                              activeStream: undefined,
                              resumable: false,
                            })
                          }}
                        >
                          放弃
                        </Button>
                      </div>
                    </div>
                  </div>
                )}

                <AnimatePresence mode="popLayout">
                  {messages.map((m) => (
                    <MessageBubble
                      key={m.id}
                      message={m}
                    />
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
                      正在生成...
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
                  逐知识点深入研究，为资料提供素材
                </div>
              </div>
              <SubAgentPanel
                activities={subAgentActivities}
                activeTab={activeSubAgentTab}
                onTabChange={setActiveSubAgentTab}
              />
            </div>
          )}
        </div>
      )}

      {/* ── Composer ── */}
      <div
        className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-background via-background to-transparent pt-10 pointer-events-none"
        style={showSplitPane ? { width: `${leftRatio * 100}%` } : undefined}
      >
        <div className="max-w-3xl mx-auto pointer-events-auto">
          <Collapsible open={optionsOpen} onOpenChange={setOptionsOpen}>
            <div className="flex items-center justify-between gap-3 mb-2">
              <CollapsibleTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2 text-xs text-muted-foreground hover:text-foreground"
                  disabled={isGenerating}
                >
                  {optionsOpen ? '收起选项' : '高级选项'}
                </Button>
              </CollapsibleTrigger>
              <div className="text-[10px] text-muted-foreground/70">
                未填写/默认将使用后端配置（.env）
              </div>
            </div>

            <CollapsibleContent>
              <div className="mb-3 rounded-2xl border border-border bg-card/80 backdrop-blur p-3 shadow-sm">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-muted-foreground">学科（可选）</div>
                    <Input
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      placeholder="例如：高中数学 / 大学物理 / 英语"
                      disabled={isGenerating}
                    />
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-muted-foreground">生成预设</div>
                    <Select
                      value={preset || 'default'}
                      onValueChange={(v) => {
                        if (v === 'default') {
                          setPreset('')
                          return
                        }
                        if (v === 'quick' || v === 'standard' || v === 'deep' || v === 'research') {
                          setPreset(v)
                        }
                      }}
                      disabled={isGenerating}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="默认（standard）" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="default">默认（standard）</SelectItem>
                        <SelectItem value="quick">quick（更快更短）</SelectItem>
                        <SelectItem value="standard">standard（平衡）</SelectItem>
                        <SelectItem value="deep">deep（更深更细）</SelectItem>
                        <SelectItem value="research">research（更研究型）</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-muted-foreground">示意图</div>
                    <Select
                      value={withDiagrams}
                      onValueChange={(v) => setWithDiagrams(v as TriState)}
                      disabled={isGenerating}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="默认" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="default">默认</SelectItem>
                        <SelectItem value="on">开启</SelectItem>
                        <SelectItem value="off">关闭</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-muted-foreground">题库（例题/练习）</div>
                    <Select
                      value={withQuestions}
                      onValueChange={(v) => setWithQuestions(v as TriState)}
                      disabled={isGenerating}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="默认" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="default">默认</SelectItem>
                        <SelectItem value="on">开启</SelectItem>
                        <SelectItem value="off">关闭</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-muted-foreground">额外检索工具（百科/问答/GitHub）</div>
                    <Select
                      value={enableExtraTools}
                      onValueChange={(v) => setEnableExtraTools(v as TriState)}
                      disabled={isGenerating}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="默认" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="default">默认</SelectItem>
                        <SelectItem value="on">开启</SelectItem>
                        <SelectItem value="off">关闭</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-muted-foreground">知识点数量上限（1-15）</div>
                    <Input
                      type="number"
                      min={1}
                      max={15}
                      value={maxPoints}
                      onChange={(e) => setMaxPoints(e.target.value)}
                      placeholder="留空=默认"
                      disabled={isGenerating}
                    />
                  </div>

                  <div className="space-y-1.5 sm:col-span-2">
                    <div className="text-xs font-medium text-muted-foreground">额外要求（可选）</div>
                    <Textarea
                      value={requirements}
                      onChange={(e) => setRequirements(e.target.value)}
                      placeholder="例如：更通俗一些 / 更严谨一些 / 偏直观解释 / 偏推导证明 / 强调常见误区"
                      className="min-h-[64px] resize-none"
                      disabled={isGenerating}
                      rows={2}
                    />
                  </div>
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>

          <form onSubmit={handleSubmit} className="relative group">
            <div className="relative flex items-end gap-2 p-2 rounded-2xl border bg-background shadow-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 transition-all">
               <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-xl text-muted-foreground hover:text-foreground shrink-0 mb-0.5"
                onClick={handleNewConversation}
                title="新建对话"
               >
                 <Plus className="h-5 w-5" />
               </Button>
               
               <Textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="例如：函数单调性 / 二次函数最值 / 受力分析..."
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
              
              {isGenerating ? (
                <Button
                  type="button"
                  size="icon"
                  variant="destructive"
                  className="h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all"
                  onClick={abortActiveStream}
                  title="停止生成"
                >
                  <Square className="h-4 w-4" />
                </Button>
              ) : (
                <Button
                  type="submit"
                  size="icon"
                  className={cn(
                    "h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all",
                    input.trim() ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                  )}
                  disabled={!input.trim()}
                >
                  <Send className="h-4 w-4" />
                </Button>
              )}
            </div>
          </form>
          
          <div className="text-center mt-2 text-[10px] text-muted-foreground/50">
            内容由 AI 生成，仅供参考。
          </div>
        </div>
      </div>
    </div>
  )
}
