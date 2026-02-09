import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { BookOpen, Loader2, Plus, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Textarea } from '@/components/ui/textarea'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { BrandMark } from '@/components/shared/BrandMark'
import { fetchSSE } from '@/api/client'
import { useConversationStore } from '@/stores/useConversationStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn, generateId } from '@/lib/utils'
import type { ConversationItem, Message, TaskStep } from '@/types'

type StudyMaterialsAgentEvent =
  | { event: 'thinking'; data: { content?: unknown } }
  | { event: 'tool_call'; data: { step_id?: unknown; name?: unknown; title?: unknown; arguments?: unknown } }
  | {
      event: 'tool_result'
      data: {
        step_id?: unknown
        name?: unknown
        title?: unknown
        success?: unknown
        elapsed_ms?: unknown
        output?: unknown
        error?: unknown
      }
    }
  | { event: 'content'; data: { content?: unknown; section?: unknown } }
  | { event: 'done'; data: { material?: unknown } }
  | { event: 'error'; data: { message?: unknown } }
  | { event: string; data?: unknown }

function toText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function toConversationTitle(text: string): string {
  const t = (text || '').trim()
  if (!t) return '新自学资料'
  return t.length > 18 ? `${t.slice(0, 18)}…` : t
}

type KnowledgePointStatus = 'pending' | 'active' | 'done' | 'failed'

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

function inferGroupStatus(
  steps: TaskStep[],
  fallback?: KnowledgePointStatus,
): KnowledgePointStatus {
  if (fallback) return fallback
  if (steps.some((s) => s.status === 'running')) return 'active'
  if (steps.some((s) => s.status === 'failed')) return 'failed'
  if (steps.length > 0 && steps.every((s) => s.status === 'completed')) return 'done'
  return 'pending'
}

function KnowledgeProgressHeader({
  points,
  statusByPoint,
  currentPoint,
}: {
  points: string[]
  statusByPoint: Record<string, KnowledgePointStatus>
  currentPoint: string | null
}) {
  if (!points.length) return null

  const total = points.length
  const done = points.filter((p) => statusByPoint[p] === 'done').length
  const failed = points.filter((p) => statusByPoint[p] === 'failed').length
  const percent = total ? Math.round((done / total) * 100) : 0

  const badgeVariant = (status: KnowledgePointStatus) => {
    if (status === 'pending') return 'outline'
    if (status === 'active') return 'default'
    if (status === 'failed') return 'destructive'
    return 'secondary'
  }

  return (
    <div className="sticky top-0 z-10 -mx-4 px-4 pt-2 pb-3 bg-background/75 backdrop-blur border-b border-border">
      <div className="rounded-xl border border-border bg-card shadow-sm p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-medium">知识点探索进度</div>
          <div className="text-xs text-muted-foreground tabular-nums">
            已探索 {done}/{total}
            {failed > 0 ? `（失败 ${failed}）` : ''}
          </div>
        </div>

        <div className="mt-2">
          <Progress value={percent} className="h-1.5" />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {points.map((p) => {
            const status = statusByPoint[p] || 'pending'
            const isCurrent = currentPoint === p
            return (
              <Badge
                key={p}
                variant={badgeVariant(status)}
                className={isCurrent ? 'ring-2 ring-primary/40 ring-offset-2 ring-offset-background' : ''}
              >
                {p}
              </Badge>
            )
          })}
        </div>

        {currentPoint && (
          <div className="mt-2 text-xs text-muted-foreground">
            当前探索：<span className="text-foreground">{currentPoint}</span>
          </div>
        )}
      </div>
    </div>
  )
}

function MessageBubble({
  message,
  knowledgePoints,
  statusByPoint,
  currentPoint,
}: {
  message: Message
  knowledgePoints?: string[]
  statusByPoint?: Record<string, KnowledgePointStatus>
  currentPoint?: string | null
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
        <div className="whitespace-pre-wrap">{message.content}</div>
      </div>

      {message.steps && message.steps.length > 0 && (
        (() => {
          const allSteps = message.steps || []

          const byPoint: Record<string, TaskStep[]> = {}
          const globalSteps: TaskStep[] = []
          const discoveredOrder: string[] = []

          for (const step of allSteps) {
            const kps = extractStepKnowledgePoints(step)
            if (kps.length === 1) {
              const kp = kps[0]
              if (!byPoint[kp]) {
                byPoint[kp] = []
                discoveredOrder.push(kp)
              }
              byPoint[kp].push(step)
            } else {
              globalSteps.push(step)
            }
          }

          const ordered = [
            ...(knowledgePoints || []).filter((kp) => kp && byPoint[kp]?.length),
            ...discoveredOrder.filter((kp) => !(knowledgePoints || []).includes(kp)),
          ]

          const groups = ordered
            .map((kp) => ({
              kp,
              steps: byPoint[kp] || [],
              status: inferGroupStatus((byPoint[kp] || []), statusByPoint?.[kp]),
            }))
            .filter((g) => g.kp && g.steps.length > 0)

          const badgeVariant = (status: KnowledgePointStatus) => {
            if (status === 'pending') return 'outline'
            if (status === 'active') return 'default'
            if (status === 'failed') return 'destructive'
            return 'secondary'
          }

          return (
            <div className="mt-3 overflow-hidden rounded-lg border border-border bg-card">
              <div className="px-4 py-2 text-xs text-muted-foreground flex items-center justify-between">
                <span>思考步骤（按知识点归档）</span>
                <span className="tabular-nums">{allSteps.length} 步</span>
              </div>

              {groups.length > 0 && (
                <div className="divide-y divide-border">
                  {groups.map((g) => {
                    const isCurrent = currentPoint && g.kp === currentPoint
                    return (
                      <div key={g.kp}>
                        <div className="px-4 py-2 flex items-center justify-between gap-3 bg-muted/10">
                          <div className="flex items-center gap-2 min-w-0">
                            <Badge variant={badgeVariant(g.status)} className="shrink-0">
                              {g.status === 'active'
                                ? '进行中'
                                : g.status === 'done'
                                  ? '已完成'
                                  : g.status === 'failed'
                                    ? '失败'
                                    : '待处理'}
                            </Badge>
                            <div
                              className={cn(
                                'text-sm font-medium truncate',
                                isCurrent && 'text-primary',
                              )}
                              title={g.kp}
                            >
                              {g.kp}
                            </div>
                          </div>
                          {isCurrent && (
                            <div className="text-xs text-muted-foreground shrink-0">当前</div>
                          )}
                        </div>
                        <div className="p-4 bg-muted/30">
                          <TaskTimeline steps={g.steps} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {globalSteps.length > 0 && (
                <div className="border-t border-border">
                  <div className="px-4 py-2 text-xs text-muted-foreground flex items-center justify-between bg-muted/10">
                    <span>全局步骤</span>
                    <span className="tabular-nums">{globalSteps.length} 步</span>
                  </div>
                  <div className="p-4 bg-muted/30">
                    <TaskTimeline steps={globalSteps} />
                  </div>
                </div>
              )}
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

  const [input, setInput] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [knowledgePoints, setKnowledgePoints] = useState<string[]>([])
  const [knowledgeStatus, setKnowledgeStatus] = useState<Record<string, KnowledgePointStatus>>({})
  const [currentKnowledgePoint, setCurrentKnowledgePoint] = useState<string | null>(null)

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

  const messages = useConversationStore((state) =>
    state.getMessages(activeConversationId ?? '')
  )

  const {
    startTask,
    addStep,
    updateStep,
    completeTask,
    failTask,
  } = useTaskStore()

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages.length])

  const handleNewConversation = () => {
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
    setKnowledgePoints([])
    setKnowledgeStatus({})
    setCurrentKnowledgePoint(null)
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const prompt = input.trim()
    if (!prompt || isGenerating) return

    const now = new Date().toISOString()

    // Reset per-run knowledge-point progress (populated after split tool returns)
    setKnowledgePoints([])
    setKnowledgeStatus({})
    setCurrentKnowledgePoint(null)

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

    const assistantMessageId = generateId()
    addMessage(conversationId, {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      createdAt: now,
      steps: [],
    })

    const taskId = `study-materials-${conversationId}-${Date.now()}`
    startTask(taskId)
    setIsGenerating(true)

    let runningStepId: string | null = null
    let done = false
    const stepMeta = new Map<string, { toolName: string; knowledgePoints: string[] }>()
    let assistantSteps: TaskStep[] = []
    let assistantText = ''
    let pendingText = ''
    let flushTimer: number | null = null

    const flushAssistant = () => {
      if (!pendingText) return
      assistantText += pendingText
      pendingText = ''
      useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
        content: assistantText,
      })
    }

    const syncSteps = () => {
      useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
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
        const prev = assistantSteps.find((s) => s.id === runningStepId)
        if (prev?.status === 'running') {
          updateStep(taskId, runningStepId, { status: 'completed', endTime: t })
          updateAssistantStep(runningStepId, { status: 'completed', endTime: t })
        }
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
      '/study-materials/generate',
      { query: prompt },
      (data) => {
        const evt = data as StudyMaterialsAgentEvent
        const kind = typeof (evt as any)?.event === 'string' ? (evt as any).event : ''
        const payload = (evt as any)?.data

        if (kind === 'thinking') {
          const text = toText(payload?.content) || '思考中…'
          startRunningStep(text)
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 20 })
          return
        }

        if (kind === 'tool_call') {
          const name = toText(payload?.name) || 'tool'
          const stepId = toText(payload?.step_id)
          const stepTitle = toText(payload?.title)

          const points = normalizeKnowledgePoints((payload as any)?.arguments?.knowledge_points)
          if (stepId) {
            stepMeta.set(stepId, { toolName: name, knowledgePoints: points })
          }

          if (points.length === 1) {
            const kp = points[0]
            setCurrentKnowledgePoint(kp)
            setKnowledgeStatus((prev) => {
              if (prev[kp] === 'done' || prev[kp] === 'failed') return prev
              return { ...prev, [kp]: 'active' }
            })
          }
          startRunningStep(stepTitle || `调用工具：${name}`, {
            ...(stepId ? { id: stepId } : {}),
            toolName: name,
            input: payload?.arguments,
          })
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 40 })
          return
        }

        if (kind === 'tool_result') {
          const stepId = toText(payload?.step_id) || runningStepId || ''
          if (!stepId) return
          const success = (payload as any)?.success === true
          const out = (payload as any)?.output
          const err = toText(payload?.error)
          const t = new Date().toISOString()
          const toolName = toText(payload?.name)

          updateStep(taskId, stepId, {
            status: success ? 'completed' : 'failed',
            endTime: t,
            output: out,
            error: err || undefined,
          })
          updateAssistantStep(stepId, {
            status: success ? 'completed' : 'failed',
            endTime: t,
            output: out,
            error: err || undefined,
          })
          runningStepId = null

          if (toolName === 'split_knowledge_points') {
            const points = normalizeKnowledgePoints((out as any)?.knowledge_points)
            if (points.length > 0) {
              setKnowledgePoints(points)
              setKnowledgeStatus((prev) => {
                const next: Record<string, KnowledgePointStatus> = { ...prev }
                for (const kp of points) {
                  if (!next[kp]) next[kp] = 'pending'
                }
                return next
              })
            }
          }

          const markPoints = (points: string[], status: KnowledgePointStatus) => {
            if (!points.length) return
            setKnowledgeStatus((prev) => {
              const next = { ...prev }
              for (const kp of points) {
                next[kp] = status
              }
              return next
            })
          }

          const meta = stepMeta.get(stepId)
          const points = meta?.knowledgePoints ?? []

          // Prefer tracking exploration progress by per-knowledge-point generation (most accurate for DFS + subagent runs)
          if (toolName === 'generate_study_material') {
            if (points.length === 1) {
              markPoints(points, success ? 'done' : 'failed')
              setCurrentKnowledgePoint(null)
            } else if (points.length > 1) {
              markPoints(points, success ? 'done' : 'failed')
              setCurrentKnowledgePoint(null)
            }
          }

          // Fallback: if backend only searches questions once per point but generates globally, still show progress.
          if (toolName === 'search_questions_by_knowledge') {
            if (points.length === 1) {
              const kp = points[0]
              setKnowledgeStatus((prev) => {
                if (prev[kp] === 'done' || prev[kp] === 'failed') return prev
                return { ...prev, [kp]: success ? 'done' : 'failed' }
              })
            } else if (points.length > 1) {
              markPoints(points, success ? 'done' : 'failed')
            }
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
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 70 })
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

          const md = toText(payload?.material?.markdown)
          if (md) {
            assistantText = md
            useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
              content: md,
              steps: assistantSteps,
            })
          } else {
            useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
              content: assistantText,
              steps: assistantSteps,
            })
          }

          updateConversation(conversationId!, {
            title: toConversationTitle(prompt),
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
          useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
            content: `出错：${msg}`,
            steps: assistantSteps,
          })
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), status: 'active' })
          setIsGenerating(false)
        }
      },
      (err) => {
        if (done) return
        const msg = err.message || '生成失败'
        setError(msg)
        failTask(taskId, msg)
        useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
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
            <KnowledgeProgressHeader
              points={knowledgePoints}
              statusByPoint={knowledgeStatus}
              currentPoint={currentKnowledgePoint}
            />
            <AnimatePresence mode="popLayout">
              {messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  knowledgePoints={knowledgePoints}
                  statusByPoint={knowledgeStatus}
                  currentPoint={currentKnowledgePoint}
                />
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
            内容由 AI 生成，仅供参考。
          </div>
        </div>
      </div>
    </div>
  )
}
