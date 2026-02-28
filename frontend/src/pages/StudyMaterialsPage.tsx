import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { BookOpen, ChevronLeft, ChevronRight, GripVertical, Layers, Loader2, Plus, Send, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
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
import { fetchSSERequest, resolveApiResourceUrl } from '@/api/client'
import { getStudyMaterialsTask } from '@/api/studyMaterials'
import { useConversationStore } from '@/stores/useConversationStore'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
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
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function toConversationTitle(text: string): string {
  const t = (text || '').trim()
  if (!t) return '新自学资料'
  return t.length > 18 ? `${t.slice(0, 18)}…` : t
}

type LatexLessonPlanOption = {
  id: string
  sourceType?: 'lesson_plan' | 'study_materials'
  title?: string
  subject?: string
  grade?: string
  createdAt?: string
  mdUrl: string
  mdFilename?: string
}

function extractMarkdownHref(content: string): string {
  const text = (content || '').trim()
  if (!text) return ''

  // Prefer a line mentioning Markdown (lesson-plan success messages include both Markdown and PDF links).
  const lines = text.split(/\r?\n/)
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i] || ''
    if (!/Markdown/i.test(line)) continue
    const m = line.match(/\(([^)]+)\)/)
    if (m && m[1]) return m[1].trim()
  }

  // Fallback: grab any Markdown link ending with `.md`.
  const linkRe = /\[[^\]]*\]\(([^)]+)\)/g
  let match: RegExpExecArray | null
  while ((match = linkRe.exec(text))) {
    const url = (match[1] || '').trim()
    if (!url) continue
    if (url.toLowerCase().includes('.md')) return url
  }
  return ''
}

type TriState = 'default' | 'on' | 'off'

function formatStudyMaterialsError(raw: string): string {
  const msg = (raw || '').trim()
  if (!msg) return '生成失败'

  const lower = msg.toLowerCase()
  if (lower.includes('task not found') || lower.includes('task_not_found')) {
    return '任务已丢失（可能是后端重启或任务过期）。请重新生成。'
  }
  if (lower.includes('event backlog truncated')) {
    return '任务输出过长导致回放被截断。建议重新生成以获得完整输出。'
  }
  if (lower.includes('llm_not_configured')) {
    return '未配置大模型（API Key）。请先配置后端环境变量并重启后端再试。'
  }
  if (lower.includes('llm_request_failed')) {
    return '大模型请求失败。请稍后重试，或检查 Key/模型名/网络/额度。'
  }
  if (lower.includes('markdown_empty')) {
    return '生成内容为空，请换个问题或补充更多要求后再试。'
  }
  if (lower.includes('http error! status: 401') || lower.includes('http error! status: 403')) {
    return '登录已过期或无权限，请重新登录后重试。'
  }

  return msg
}

function normalizeKnowledgePoints(points: unknown): string[] {
  if (!Array.isArray(points)) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of points) {
    const text = typeof item === 'string' ? item.trim() : ''
    if (!text) continue
    if (/^(?:\.\.\.|…)(?:\s*(?:[（(]\s*)?共\s*\d+\s*项(?:\s*[)）])?)?\s*$/u.test(text)) {
      continue
    }
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
            <motion.button
              key={activity.knowledgePoint}
              onClick={() => onTabChange(activity.knowledgePoint)}
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18 }}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors',
                isActive
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
              )}
            >
              {statusIcon(activity.status)}
              <span>{activity.knowledgePoint}</span>
            </motion.button>
          )
        })}
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-auto p-4 min-h-0 overscroll-contain">
        <AnimatePresence mode="popLayout">
          {selectedActivity ? (
            <motion.div
              key={selectedKP}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.18 }}
            >
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
            </motion.div>
          ) : (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="text-sm text-muted-foreground"
            >
              选择一个知识点查看详情
            </motion.div>
          )}
        </AnimatePresence>
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

  const [subAgentCollapsed, setSubAgentCollapsed] = useState(false)

  // Advanced options (optional; when unset, backend uses `.env` defaults)
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [subject, setSubject] = useState('')
  const [preset, setPreset] = useState<'quick' | 'standard' | 'deep' | 'research' | ''>('')
  const [requirements, setRequirements] = useState('')
  const [withQuestions, setWithQuestions] = useState<TriState>('default')
  const [withDiagrams, setWithDiagrams] = useState<TriState>('default')
  const [enableExtraTools, setEnableExtraTools] = useState<TriState>('default')
  const [maxPoints, setMaxPoints] = useState<string>('')

  const [latexDialogOpen, setLatexDialogOpen] = useState(false)
  const [latexLessonPlanId, setLatexLessonPlanId] = useState('')
  const [latexFileName, setLatexFileName] = useState('')
  const [latexTopic, setLatexTopic] = useState('')
  const [latexSubject, setLatexSubject] = useState('')
  const [latexMarkdown, setLatexMarkdown] = useState('')
  const [latexIsConverting, setLatexIsConverting] = useState(false)
  const [latexError, setLatexError] = useState<string | null>(null)
  const latexSourceAbortRef = useRef<AbortController | null>(null)
  const [latexIsLoadingSource, setLatexIsLoadingSource] = useState(false)
  const latexConvertAbortRef = useRef<AbortController | null>(null)
  const [latexProgressPercent, setLatexProgressPercent] = useState(0)
  const [latexProgressStage, setLatexProgressStage] = useState('')
  const [latexTexUrl, setLatexTexUrl] = useState('')
  const [latexTexFilename, setLatexTexFilename] = useState('')
  const [latexTexText, setLatexTexText] = useState('')
  const [latexNotice, setLatexNotice] = useState<string | null>(null)

  const conversations = useConversationStore((state) => state.conversations)
  const currentConversationId = useConversationStore((state) => state.currentConversationIdByType.study_materials)
  const addConversation = useConversationStore((state) => state.addConversation)
  const setCurrentConversation = useConversationStore((state) => state.setCurrentConversation)
  const updateConversation = useConversationStore((state) => state.updateConversation)
  const setMessages = useConversationStore((state) => state.setMessages)
  const addMessage = useConversationStore((state) => state.addMessage)

  const messagesByConversation = useConversationStore((state) => state.messagesByConversation)

  const lessonPlansById = useLessonPlanStore((state) => state.plansById)

  const latexLessonPlanOptions = useMemo((): LatexLessonPlanOption[] => {
    const options: LatexLessonPlanOption[] = []

    for (const p of Object.values(lessonPlansById || {})) {
      const id = toText((p as any)?.id).trim()
      const mdUrl = toText((p as any)?.mdUrl).trim()
      if (!id || !mdUrl) continue

      options.push({
        id,
        sourceType: 'lesson_plan',
        title: toText((p as any)?.title) || undefined,
        subject: toText((p as any)?.subject) || undefined,
        grade: toText((p as any)?.grade) || undefined,
        createdAt: toText((p as any)?.createdAt) || undefined,
        mdUrl,
        mdFilename: toText((p as any)?.mdFilename) || undefined,
      })
    }

    const seen = new Set(options.map((o) => o.id))
    for (const c of conversations || []) {
      if (!c || (c.type !== 'lesson_plan' && c.type !== 'study_materials')) continue
      const cid = toText(c.id).trim()
      if (!cid) continue
      if (seen.has(cid)) continue

      const msgs = (messagesByConversation as any)?.[cid]
      const list = Array.isArray(msgs) ? (msgs as Message[]) : []

      let mdUrl = ''
      for (let i = list.length - 1; i >= 0; i--) {
        const href = extractMarkdownHref(toText(list[i]?.content))
        if (href) {
          mdUrl = href
          break
        }
      }
      if (!mdUrl) continue

      options.push({
        id: cid,
        sourceType: c.type === 'study_materials' ? 'study_materials' : 'lesson_plan',
        title: toText(c.title) || undefined,
        createdAt: toText(c.createdAt) || undefined,
        mdUrl,
      })
      seen.add(cid)
    }

    options.sort((a, b) => {
      const ta = toText(a.createdAt)
      const tb = toText(b.createdAt)
      if (!ta && !tb) return 0
      if (!ta) return 1
      if (!tb) return -1
      return tb.localeCompare(ta)
    })

    return options
  }, [lessonPlansById, conversations, messagesByConversation])

  const latexLessonPlanOptionById = useMemo(() => {
    const out: Record<string, LatexLessonPlanOption> = {}
    for (const opt of latexLessonPlanOptions) out[opt.id] = opt
    return out
  }, [latexLessonPlanOptions])

  const activeConversationId = useMemo(() => {
    if (!currentConversationId) return null
    const current = conversations.find((c) => c.id === currentConversationId)
    return current?.type === 'study_materials' ? currentConversationId : null
  }, [conversations, currentConversationId])

  const activeConversation = useMemo(() => {
    if (!activeConversationId) return null
    return conversations.find((c) => c.id === activeConversationId) ?? null
  }, [conversations, activeConversationId])

  const activeStream = activeConversation?.activeStream
  const hasResumableStream = Boolean(activeConversation?.resumable && activeStream?.taskId)
  const lastTask = activeConversation?.lastTask
  const isGenerating = isGeneratingLocal

  const messages = useConversationStore((state) =>
    state.getMessages(activeConversationId ?? '')
  )

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages.length])

  const hasSubAgentPane = isGenerating || subAgentActivities.length > 0

  useEffect(() => {
    if (!hasSubAgentPane) {
      setSubAgentCollapsed(false)
    }
  }, [hasSubAgentPane])

  // Reconstruct subAgentActivities from persisted messages on load / conversation switch
  useEffect(() => {
    if (!activeConversationId) return
    if (isGeneratingLocal) return // don't overwrite while streaming

    const msgs = useConversationStore.getState().getMessages(activeConversationId)
    const allSteps: TaskStep[] = []
    for (const m of msgs) {
      if (m.role === 'assistant' && Array.isArray(m.steps)) {
        allSteps.push(...m.steps)
      }
    }
    if (allSteps.length === 0) return

    // Find the split_knowledge_points result to get the full KP list
    let kpList: string[] = []
    for (const step of allSteps) {
      if (step.toolName === 'split_knowledge_points' && step.output && typeof step.output === 'object') {
        const out = step.output as Record<string, unknown>
        kpList = normalizeKnowledgePoints(out.knowledge_points)
        if (kpList.length > 0) break
      }
    }
    if (kpList.length === 0) return

    // Collect per-KP steps
    const kpStepsMap = new Map<string, TaskStep[]>()
    for (const kp of kpList) kpStepsMap.set(kp, [])

    for (const step of allSteps) {
      const stepKps = extractStepKnowledgePoints(step)
      if (stepKps.length === 1 && kpStepsMap.has(stepKps[0])) {
        kpStepsMap.get(stepKps[0])!.push(step)
      }
    }

    const activities: SubAgentActivity[] = kpList.map((kp) => {
      const steps = kpStepsMap.get(kp) || []
      let status: SubAgentActivity['status'] = 'pending'
      if (steps.length > 0) {
        const hasRunning = steps.some((s) => s.status === 'running')
        const hasFailed = steps.some((s) => s.status === 'failed')
        if (hasRunning) status = 'running'
        else if (hasFailed) status = 'failed'
        else status = 'completed'
      }
      return { knowledgePoint: kp, status, steps }
    })

    setSubAgentActivities(activities)
    setActiveSubAgentTab((prev) => prev || kpList[0])
  }, [activeConversationId, isGeneratingLocal])

  const abortActiveStream = useCallback(() => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort()
      streamAbortRef.current = null
    }
    streamKeyRef.current = null
    setIsGeneratingLocal(false)
  }, [])

  // Sidebar "new conversation" clears the current conversation selection but does not reset
  // page-local React state. Reset here so the UI is actually clean.
  useEffect(() => {
    if (activeConversationId) return
    abortActiveStream()
    setInput('')
    setError(null)
    setSubAgentActivities([])
    setActiveSubAgentTab(null)
  }, [activeConversationId, abortActiveStream])

  const openLatexDialog = () => {
    if (!latexSubject.trim()) setLatexSubject(subject)
    setLatexDialogOpen(true)
  }

  const handlePickLessonPlanMarkdown = async (planId: string) => {
    const resolvedId = toText(planId).trim()
    setLatexLessonPlanId(resolvedId)

    if (latexSourceAbortRef.current) {
      latexSourceAbortRef.current.abort()
      latexSourceAbortRef.current = null
    }

    setLatexError(null)
    setLatexNotice(null)
    setLatexProgressPercent(0)
    setLatexProgressStage('')
    setLatexTexUrl('')
    setLatexTexFilename('')
    setLatexTexText('')
    setLatexMarkdown('')
    setLatexFileName('')

    if (!resolvedId) return

    const plan = latexLessonPlanOptionById[resolvedId]
    const mdUrl = toText(plan?.mdUrl)
    if (!mdUrl) {
      setLatexError('未找到 Markdown，请先成功生成内容后再试。')
      return
    }

    const topic = toText(plan?.title)
    if (topic) setLatexTopic(topic)
    const subj = toText(plan?.subject)
    if (subj) setLatexSubject(subj)
    setLatexFileName(toText(plan?.mdFilename))

    const controller = new AbortController()
    latexSourceAbortRef.current = controller
    setLatexIsLoadingSource(true)
    try {
      const href = resolveApiResourceUrl(mdUrl)
      const res = await fetch(href, { signal: controller.signal })
      if (!res.ok) {
        throw new Error(`加载 Markdown 失败（${res.status}）`)
      }
      const text = await res.text()
      setLatexMarkdown(text)
    } catch (err: any) {
      const msg = toText(err?.message) || '加载 Markdown 失败'
      setLatexError(formatStudyMaterialsError(msg))
    } finally {
      setLatexIsLoadingSource(false)
      if (latexSourceAbortRef.current === controller) {
        latexSourceAbortRef.current = null
      }
    }
  }

  const clearLatexLessonPlanSelection = () => {
    void handlePickLessonPlanMarkdown('')
  }

  const handleConvertToLatex = async () => {
    const md = (latexMarkdown || '').trim()
    if (!md || latexIsConverting || latexIsLoadingSource || !latexLessonPlanId.trim()) return

    if (latexConvertAbortRef.current) {
      latexConvertAbortRef.current.abort()
      latexConvertAbortRef.current = null
    }
    const controller = new AbortController()
    latexConvertAbortRef.current = controller

    setLatexIsConverting(true)
    setLatexError(null)
    setLatexNotice(null)
    setLatexProgressPercent(0)
    setLatexProgressStage('')
    setLatexTexUrl('')
    setLatexTexFilename('')
    setLatexTexText('')

    try {
      let donePayload: any = null

      await fetchSSERequest(
        '/study-materials/convert-markdown-to-latex/stream',
        {
          method: 'POST',
          body: {
            markdown: md,
            topic: latexTopic.trim(),
            subject: latexSubject.trim(),
          },
          signal: controller.signal,
        },
        (data) => {
          const evt = data as any
          const kind = typeof evt?.event === 'string' ? evt.event : ''
          const payload = evt?.data

          if (kind === 'status') {
            const text = toText(payload?.content)
            if (text) setLatexProgressStage(text)
            return
          }

          if (kind === 'progress') {
            const percentRaw = payload?.percent
            const percent =
              typeof percentRaw === 'number' ? percentRaw : typeof percentRaw === 'string' ? Number(percentRaw) : NaN
            if (Number.isFinite(percent)) {
              setLatexProgressPercent(Math.max(0, Math.min(100, percent as number)))
            }
            const stage = toText(payload?.stage)
            if (stage) setLatexProgressStage(stage)
            return
          }

          if (kind === 'done') {
            donePayload = payload
            return
          }

          if (kind === 'error') {
            const msg = formatStudyMaterialsError(toText(payload?.message) || '转换失败')
            setLatexError(msg)
            return
          }
        },
        (err) => {
          const msg = formatStudyMaterialsError(toText((err as any)?.message) || '转换失败')
          setLatexError(msg)
        }
      )

      const texUrl = toText(donePayload?.tex_url)
      const filename = toText(donePayload?.filename)

      if (!texUrl) {
        throw new Error('转换失败')
      }

      setLatexTexUrl(texUrl)
      setLatexTexFilename(filename)

      setLatexProgressPercent(100)
      setLatexProgressStage('加载 LaTeX…')

      const href = resolveApiResourceUrl(texUrl)
      const texRes = await fetch(href)
      const texText = await texRes.text()
      setLatexTexText(texText)
    } catch (err: any) {
      const msg = toText(err?.message) || '转换失败'
      setLatexError(formatStudyMaterialsError(msg))
    } finally {
      setLatexIsConverting(false)
      if (latexConvertAbortRef.current === controller) {
        latexConvertAbortRef.current = null
      }
    }
  }

  const handleCopyLatex = async () => {
    const tex = (latexTexText || '').trim()
    if (!tex) return
    try {
      await navigator.clipboard.writeText(tex)
      setLatexNotice('已复制')
      window.setTimeout(() => setLatexNotice(null), 1600)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '复制失败'
      setLatexError(msg)
    }
  }

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

    // Streaming "thinking" panel (auto-expanded while running, auto-collapsed when finished).
    let thinkingStepId: string | null = null
    let thinkingStartTime: string | null = null
    let thinkingBuffer = ''

    let runningSubAgentKP: string | null = null
    const subThinkingStepIdByKP: Record<string, string> = {}
    const subThinkingStartTimeByKP: Record<string, string> = {}
    const subThinkingBufferByKP: Record<string, string> = {}

    const upsertSubAgentStep = (kp: string, step: TaskStep) => {
      setSubAgentActivities((prev) => {
        const exists = prev.some((a) => a.knowledgePoint === kp)
        const base = exists ? prev : [...prev, { knowledgePoint: kp, status: 'pending' as const, steps: [] }]
        return base.map((a) => {
          if (a.knowledgePoint !== kp) return a
          const hasStep = a.steps.some((s) => s.id === step.id)
          const steps = hasStep ? a.steps.map((s) => (s.id === step.id ? { ...s, ...step } : s)) : [...a.steps, step]
          return { ...a, steps }
        })
      })
    }

    const patchSubAgentStep = (kp: string, stepId: string, patch: Partial<TaskStep>) => {
      setSubAgentActivities((prev) =>
        prev.map((a) => {
          if (a.knowledgePoint !== kp) return a
          const hasStep = a.steps.some((s) => s.id === stepId)
          if (!hasStep) {
            return {
              ...a,
              steps: [
                ...a.steps,
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
              ],
            }
          }
          return { ...a, steps: a.steps.map((s) => (s.id === stepId ? { ...s, ...patch } : s)) }
        })
      )
    }

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
        lastTask: {
          taskType: 'study_materials',
          taskId: serverTaskId,
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
              lastTask: {
                taskType: 'study_materials',
                taskId,
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
          const raw = toText(payload?.message)
          const msg = raw ? formatStudyMaterialsError(raw) : ''
          if (msg) setError(msg)
          return
        }

        if (kind === 'thinking') {
          const text = toText(payload?.content) || '思考中…'
          const t = new Date().toISOString()

          if (runningSubAgentKP) {
            const kp = runningSubAgentKP
            if (!subThinkingStepIdByKP[kp]) {
              subThinkingStepIdByKP[kp] = `thinking-${generateId()}`
              subThinkingStartTimeByKP[kp] = t
              subThinkingBufferByKP[kp] = ''
              upsertSubAgentStep(kp, {
                id: subThinkingStepIdByKP[kp],
                title: '思考（子智能体）',
                status: 'running',
                startTime: subThinkingStartTimeByKP[kp],
                toolName: 'thinking',
                output: '',
              })
            }

            subThinkingBufferByKP[kp] = subThinkingBufferByKP[kp]
              ? `${subThinkingBufferByKP[kp]}\n${text}`
              : text
            patchSubAgentStep(kp, subThinkingStepIdByKP[kp], { output: subThinkingBufferByKP[kp] })
            return
          }

          if (!thinkingStepId) {
            thinkingStepId = `thinking-${generateId()}`
            thinkingStartTime = t
            thinkingBuffer = ''
            upsertAssistantStep({
              id: thinkingStepId,
              title: '思考',
              status: 'running',
              startTime: thinkingStartTime,
              toolName: 'thinking',
              output: '',
            })
          }
          thinkingBuffer = thinkingBuffer ? `${thinkingBuffer}\n${text}` : text
          patchAssistantStep(thinkingStepId, { output: thinkingBuffer })
          return
        }

        if (kind === 'tool_call') {
          const name = toText(payload?.name) || 'tool'

          // Close the current thinking step when the agent starts executing tools.
          if (thinkingStepId) {
            const tThinking = new Date().toISOString()
            patchAssistantStep(thinkingStepId, { status: 'completed', endTime: tThinking })
          }

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
                a.knowledgePoint === kp ? { ...a, steps: [...a.steps, step] } : a
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

          // Initialize/refresh subAgentActivities when knowledge points are produced/reviewed
          if ((toolName === 'split_knowledge_points' || toolName === 'review_knowledge_points') && out && typeof out === 'object') {
            const kps = normalizeKnowledgePoints((out as any).knowledge_points)
            if (kps.length > 0) {
              setSubAgentActivities(
                kps.map((kp) => ({
                  knowledgePoint: kp,
                  status: 'pending' as const,
                  steps: [],
                }))
              )
              setActiveSubAgentTab((prev) => prev || kps[0])
            }
          }
          return
        }

        if (kind === 'subagent_start') {
          const kp = toText(payload?.knowledge_point)
          if (kp) {
            runningSubAgentKP = kp
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
            if (runningSubAgentKP === kp) runningSubAgentKP = null
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
          if (thinkingStepId) {
            patchAssistantStep(thinkingStepId, { status: 'completed', endTime: t })
          }
          const mdUrl = toText(payload?.material?.md_url)
          const texUrl = toText(payload?.material?.tex_url)
          const pdfUrl = toText(payload?.material?.pdf_url)
          const mdFilename = toText(payload?.material?.md_filename)
          const texFilename = toText(payload?.material?.tex_filename)
          const pdfFilename = toText(payload?.material?.pdf_filename)
          const fatal = payload?.material?.error as any
          const fatalTool = toText(fatal?.tool)
          const fatalMsg = toText(fatal?.error)

          const mdHref = mdUrl ? resolveApiResourceUrl(mdUrl) : ''
          const texHref = texUrl ? resolveApiResourceUrl(texUrl) : ''
          const pdfHref = pdfUrl ? resolveApiResourceUrl(pdfUrl) : ''

          const downloads: string[] = []
          if (mdHref || texHref || pdfHref) {
            downloads.push('---', '## 下载', '')
            downloads.push(
              mdHref
                ? `- Markdown： [${mdFilename ? `下载（${mdFilename}）` : '下载 Markdown'}](${mdHref})`
                : '- Markdown： （生成失败或未导出）'
            )
            downloads.push(
              texHref
                ? `- LaTeX： [${texFilename ? `下载（${texFilename}）` : '下载 LaTeX'}](${texHref})`
                : '- LaTeX： （未生成）'
            )
            downloads.push(
              pdfHref
                ? `- PDF： [${pdfFilename ? `下载（${pdfFilename}）` : '下载 PDF'}](${pdfHref})`
                : '- PDF： （生成失败或未编译）'
            )
          }

          const isExportFailure = ['convert_markdown_to_latex', 'refine_latex', 'compile_latex_to_pdf'].includes(fatalTool)
          const interrupt =
            fatalTool || fatalMsg
              ? `**${isExportFailure ? 'LaTeX/PDF 导出失败' : '生成中断'}**：${[fatalTool, fatalMsg].filter(Boolean).join(' - ')}`
              : ''

          let content = (assistantText || '已完成生成。').trimEnd()
          if (downloads.length > 0) {
            content = [content, '', ...downloads].join('\n')
          }
          if (interrupt) {
            content = [content, '', interrupt].join('\n')
          }

          useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
            content,
            steps: assistantSteps,
          })

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
          const msg = formatStudyMaterialsError(toText(payload?.message) || '生成失败')
          setError(msg)

          const t = new Date().toISOString()
          if (thinkingStepId) {
            patchAssistantStep(thinkingStepId, { status: 'failed', endTime: t, error: msg })
          }

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

        const msg = formatStudyMaterialsError(err.message || '生成失败')
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

  const resumeStudyMaterialsStreamWithProbe = useCallback(
    async (opts: {
      conversationId: string
      assistantMessageId: string
      taskId: string
      afterSeq: number
    }) => {
      const conversationId = opts.conversationId
      const assistantMessageId = opts.assistantMessageId
      const taskId = String(opts.taskId || '').trim()
      const afterSeq = Number.isFinite(opts.afterSeq) ? opts.afterSeq : 0

      if (!taskId) return
      if (isGeneratingLocal) return

      try {
        const status = await getStudyMaterialsTask(taskId)
        if (status.status !== 'running') {
          useConversationStore.getState().updateConversation(conversationId, {
            activeStream: undefined,
            resumable: false,
          })
          return
        }
      } catch {
        useConversationStore.getState().updateConversation(conversationId, {
          activeStream: undefined,
          resumable: false,
        })
        setError('任务已丢失（可能是后端重启或任务过期）。请重新生成。')
        return
      }

      runStudyMaterialsStream({
        conversationId,
        assistantMessageId,
        request: {
          url: `/study-materials/tasks/${encodeURIComponent(taskId)}/stream?after_seq=${afterSeq}`,
          method: 'GET',
        },
        initialTaskId: taskId,
        initialSeq: afterSeq,
        streamKey: `${conversationId}:${taskId}`,
      })
    },
    [isGeneratingLocal, runStudyMaterialsStream]
  )

  const activeStreamTaskId = activeConversation?.activeStream?.taskId
  const activeStreamAssistantMessageId = activeConversation?.activeStream?.assistantMessageId
  const activeStreamLastSeq = activeConversation?.activeStream?.lastSeq

  // Resume after refresh: if a conversation has an active stream, reconnect from last seq.
  useEffect(() => {
    if (!activeConversationId) return
    if (!activeStreamTaskId || !activeStreamAssistantMessageId) return

    const key = `${activeConversationId}:${activeStreamTaskId}`
    if (streamKeyRef.current === key) return
    void resumeStudyMaterialsStreamWithProbe({
      conversationId: activeConversationId,
      assistantMessageId: activeStreamAssistantMessageId,
      taskId: activeStreamTaskId,
      afterSeq: Number(activeStreamLastSeq || 0),
    })
  }, [
    activeConversationId,
    activeStreamTaskId,
    activeStreamAssistantMessageId,
    activeStreamLastSeq,
    resumeStudyMaterialsStreamWithProbe,
  ])

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
      type: 'study_materials',
      createdAt: now,
      updatedAt: now,
      status: 'active',
      resumable: false,
    }
    addConversation(item)
    setCurrentConversation(id, 'study_materials')
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

    const normalized = prompt.replace(/\s+/g, '').trim().toLowerCase()
    const isContinueIntent =
      normalized === '继续' ||
      normalized === '接着' ||
      normalized === '续写' ||
      normalized === '继续生成' ||
      normalized === '继续输出' ||
      normalized === 'continue' ||
      normalized === 'resume'

    if (isContinueIntent && activeConversationId && activeStream?.taskId && activeStream.assistantMessageId) {
      const now = new Date().toISOString()
      addMessage(activeConversationId, {
        id: generateId(),
        role: 'user',
        content: prompt,
        createdAt: now,
      })
      setInput('')
      setError(null)
      void resumeStudyMaterialsStreamWithProbe({
        conversationId: activeConversationId,
        assistantMessageId: activeStream.assistantMessageId,
        taskId: activeStream.taskId,
        afterSeq: Number(activeStream.lastSeq || 0),
      })
      return
    }

    const now = new Date().toISOString()

    // Ensure a study-materials conversation is selected
    let conversationId = activeConversationId
    if (!conversationId) {
      conversationId = generateId()
      const conversation: ConversationItem = {
        id: conversationId,
        title: toConversationTitle(prompt),
        type: 'study_materials',
        createdAt: now,
        updatedAt: now,
        status: 'active',
        resumable: false,
        progress: 0,
      }
      addConversation(conversation)
      setCurrentConversation(conversationId, 'study_materials')
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

  const startContinueIteration = useCallback(
    (mode: 'improve' | 'deepen_research' | 'fix_export' | 'skip_export') => {
      if (!activeConversationId) return
      const baseTaskId = String(lastTask?.taskId || '').trim()
      if (!baseTaskId) return
      if (isGenerating) return

      const now = new Date().toISOString()
      const userText =
        mode === 'deepen_research'
          ? '继续迭代：加深检索与补充边界/反例'
          : mode === 'fix_export'
            ? '继续：修复导出（LaTeX/PDF）'
            : mode === 'skip_export'
              ? '继续：跳过导出，完成其余内容'
              : '继续迭代优化'

      addMessage(activeConversationId, {
        id: generateId(),
        role: 'user',
        content: userText,
        createdAt: now,
      })

      setError(null)
      setSubAgentActivities([])
      setActiveSubAgentTab(null)

      const assistantMessageId = generateId()
      addMessage(activeConversationId, {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        createdAt: now,
        steps: [],
      })

      updateConversation(activeConversationId, {
        updatedAt: now,
        status: 'active',
        progress: 0,
        activeStream: undefined,
        resumable: false,
      })

      const localTaskId = `study-materials-${activeConversationId}-${Date.now()}-continue`
      useTaskStore.getState().startTask(localTaskId)

      runStudyMaterialsStream({
        conversationId: activeConversationId,
        assistantMessageId,
        request: {
          url: `/study-materials/tasks/${encodeURIComponent(baseTaskId)}/continue`,
          method: 'POST',
          body: { mode },
        },
        localTaskId,
        initialSeq: 0,
        streamKey: `${activeConversationId}:${assistantMessageId}`,
      })
    },
    [activeConversationId, lastTask?.taskId, isGenerating, addMessage, updateConversation, runStudyMaterialsStream]
  )

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const showSplitPane = hasSubAgentPane && !subAgentCollapsed

  return (
    <div ref={containerRef} className="h-full flex flex-col relative overflow-hidden min-h-0">
      {/* Messages area (or welcome) */}
      {messages.length === 0 && !hasSubAgentPane ? (
        <WelcomeScreen onExampleClick={(text) => setInput(text)} />
      ) : (
        <div className="flex-1 flex overflow-hidden min-h-0 relative">
          {/* ── Left column: Main agent (chat + steps) ── */}
          <div
            className="flex flex-col overflow-hidden"
            style={{ width: showSplitPane ? `${leftRatio * 100}%` : '100%' }}
          >
            <div ref={scrollRef} className="flex-1 overflow-auto p-4 pb-32 overscroll-contain min-h-0">
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
                            void resumeStudyMaterialsStreamWithProbe({
                              conversationId: activeConversationId,
                              assistantMessageId: activeStream.assistantMessageId,
                              taskId: activeStream.taskId,
                              afterSeq: Number(activeStream.lastSeq || 0),
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

                {!isGenerating &&
                  activeConversationId &&
                  activeConversation?.status === 'completed' &&
                  lastTask?.taskId && (
                    <div className="mt-3 mb-4 rounded-xl border border-border bg-card p-3 text-sm">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-muted-foreground">
                          任务已完成。你可以继续迭代优化（会触发新一轮生成并更新下载链接）。
                        </div>
                        <div className="flex items-center gap-2">
                          <Button size="sm" onClick={() => startContinueIteration('improve')}>
                            继续迭代优化
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => startContinueIteration('deepen_research')}>
                            加深检索
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
              className="flex flex-col overflow-hidden border-l border-border bg-muted/20 min-h-0"
              style={{ width: `${(1 - leftRatio) * 100}%` }}
            >
              <div className="px-4 py-3 border-b border-border bg-background/50 backdrop-blur-sm flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Layers className="h-4 w-4 text-primary" />
                    SubAgent 工作区
                  </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  逐知识点深入研究，为资料提供素材
                </div>
              </div>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 shrink-0"
                  onClick={() => setSubAgentCollapsed(true)}
                  title="收起"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
              <SubAgentPanel
                activities={subAgentActivities}
                activeTab={activeSubAgentTab}
                onTabChange={setActiveSubAgentTab}
              />
            </div>
          )}

          {!showSplitPane && hasSubAgentPane && (
            <Button
              type="button"
              size="icon"
              variant="secondary"
              className="absolute right-2 top-3 z-20 h-9 w-9 rounded-full shadow"
              onClick={() => setSubAgentCollapsed(false)}
              title="展开 SubAgent"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
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
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 px-2 text-xs"
                  onClick={openLatexDialog}
                  disabled={isGenerating}
                >
                  MD→LaTeX
                </Button>
                <div className="text-[10px] text-muted-foreground/70">
                  未填写/默认将使用后端配置（.env）
                </div>
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

      <Dialog open={latexDialogOpen} onOpenChange={setLatexDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-auto">
          <DialogHeader>
            <DialogTitle>Markdown → LaTeX</DialogTitle>
            <DialogDescription>从已生成的 Markdown（自学资料/教案）中选择，AI 将转换为可下载的 LaTeX（.tex）。</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">选择 Markdown 来源</div>
                <Select
                  value={latexLessonPlanId}
                  onValueChange={(v) => void handlePickLessonPlanMarkdown(v)}
                  disabled={latexIsConverting || latexIsLoadingSource}
                >
                  <SelectTrigger>
                    <SelectValue
                      placeholder={latexLessonPlanOptions.length > 0 ? '请选择…' : '暂无可选 Markdown（请先生成内容）'}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {latexLessonPlanOptions.length === 0 ? (
                      <SelectItem value="__empty" disabled>
                        暂无可选 Markdown（请先生成内容）
                      </SelectItem>
                    ) : (
                      latexLessonPlanOptions.filter((p: any) => toText(p?.id).trim().length > 0).map((p: any) => (
                        <SelectItem key={toText(p?.id).trim()} value={toText(p?.id).trim()}>
                          {(`${p?.sourceType === 'study_materials' ? '自学资料' : '教案'}：${toText(p?.title) || (p?.sourceType === 'study_materials' ? '自学资料' : '教案')}`) +
                            (toText(p?.subject) ? ` · ${toText(p?.subject)}` : '') +
                            (toText(p?.grade) ? ` · ${toText(p?.grade)}` : '')}
                        </SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10px] text-muted-foreground truncate">
                    {latexFileName ? `文件：${latexFileName}` : null}
                  </div>
                  {latexIsLoadingSource ? (
                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      加载中
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">标题（可选）</div>
                <Input
                  value={latexTopic}
                  onChange={(e) => setLatexTopic(e.target.value)}
                  placeholder="用于 LaTeX 标题（可选）"
                  disabled={latexIsConverting}
                />
              </div>

              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">学科（可选）</div>
                <Input
                  value={latexSubject}
                  onChange={(e) => setLatexSubject(e.target.value)}
                  placeholder="例如：高中数学 / 大学物理"
                  disabled={latexIsConverting}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs font-medium text-muted-foreground">Markdown 内容</div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={clearLatexLessonPlanSelection}
                  disabled={latexIsConverting || latexIsLoadingSource || (!latexLessonPlanId && !latexMarkdown)}
                >
                  清除选择
                </Button>
              </div>
              <Textarea
                value={latexMarkdown}
                className="min-h-[180px] font-mono text-xs"
                placeholder="请先选择一个已成功生成的 Markdown"
                readOnly
                disabled={latexIsConverting || latexIsLoadingSource}
              />
            </div>

            {latexIsConverting && (
              <div className="rounded-xl border border-border bg-muted/20 p-3 space-y-2">
                <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <div className="truncate">{latexProgressStage || '转换中…'}</div>
                  <div className="shrink-0">{latexProgressPercent}%</div>
                </div>
                <Progress value={latexProgressPercent} className="h-2" />
              </div>
            )}

            {latexError && (
              <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-3 text-sm text-destructive flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-destructive shrink-0" />
                {latexError}
              </div>
            )}

            {latexTexUrl && (
              <div className="rounded-xl border border-border bg-muted/20 p-3 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-xs text-muted-foreground">
                    {latexTexFilename ? `已生成：${latexTexFilename}` : '已生成 LaTeX'}
                    {latexNotice ? <span className="ml-2">（{latexNotice}）</span> : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 px-2 text-xs"
                      onClick={handleCopyLatex}
                      disabled={!latexTexText}
                    >
                      复制 LaTeX
                    </Button>
                    <Button asChild size="sm" className="h-8 px-2 text-xs">
                      <a
                        href={resolveApiResourceUrl(latexTexUrl)}
                        target="_blank"
                        rel="noreferrer"
                        download={latexTexFilename || ''}
                      >
                        下载 .tex
                      </a>
                    </Button>
                  </div>
                </div>
                <Textarea
                  value={latexTexText}
                  readOnly
                  className="min-h-[220px] font-mono text-xs"
                  placeholder="LaTeX 输出将显示在这里"
                />
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setLatexDialogOpen(false)}
              disabled={latexIsConverting}
            >
              关闭
            </Button>
            <Button
              type="button"
              onClick={handleConvertToLatex}
              disabled={latexIsConverting || latexIsLoadingSource || !latexLessonPlanId || !latexMarkdown.trim()}
            >
              {latexIsConverting && <Loader2 className="h-4 w-4 animate-spin" />}
              开始转换
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
