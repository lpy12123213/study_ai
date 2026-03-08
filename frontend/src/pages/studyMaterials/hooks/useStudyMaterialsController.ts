import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, downloadText, fetchSSERequest, isApiError, resolveApiResourceUrl } from '@/api/client'
import { getStudyMaterialsTask } from '@/api/studyMaterials'
import { useFormDraft } from '@/hooks/useFormDraft'
import { useStickToBottom } from '@/hooks/useStickToBottom'
import { useAuthStore } from '@/stores/useAuthStore'
import { useConversationStore } from '@/stores/useConversationStore'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { generateId } from '@/lib/utils'
import { normalizeSseEnvelope } from '@/lib/sse'
import {
  toConversationTitle,
  toText,
  extractMarkdownHref,
  formatStudyMaterialsError,
  normalizeKnowledgePoints,
  extractStepKnowledgePoints,
} from '@/pages/studyMaterials/utils'
import type { ConversationItem, Message, TaskStep } from '@/types'
import type { LatexLessonPlanOption, SubAgentActivity, TriState } from '@/pages/studyMaterials/types'
import * as tasksApi from '@/api/tasks'

type StudyMaterialsPreset = '' | 'quick' | 'standard' | 'deep' | 'research'

function toStudyMaterialsPreset(value: unknown): StudyMaterialsPreset {
  const v = String(value ?? '').trim()
  if (v === 'quick' || v === 'standard' || v === 'deep' || v === 'research') return v
  return ''
}

export function useStudyMaterialsController() {
  const stick = useStickToBottom({ thresholdPx: 120 })
  const scrollRef = stick.containerRef
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const streamAbortRef = useRef<AbortController | null>(null)
  const streamKeyRef = useRef<string | null>(null)
  const userId = useAuthStore((s) => s.user?.id || '')
  const [searchParams, setSearchParams] = useSearchParams()
  const reuseTaskId = String(searchParams.get('reuse_task') || '').trim()

  const [input, setInput] = useState('')
  const [isGeneratingLocal, setIsGeneratingLocal] = useState(false)
  const [error, setError] = useState<unknown>(null)

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
  const [preset, setPreset] = useState<StudyMaterialsPreset>('')
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
  const lastTaskErrorTool = toText(lastTask?.materialError?.tool)
  const isLastExportFailure = ['convert_markdown_to_latex', 'refine_latex', 'compile_latex_to_pdf'].includes(lastTaskErrorTool)
  const isGenerating = isGeneratingLocal

  const draftKey = `draft:study-materials:v1:${userId || 'anon'}`
  const { clearDraft } = useFormDraft({
    storageKey: draftKey,
    enabled: !activeConversationId && !isGeneratingLocal,
    value: {
      input,
      subject,
      preset,
      requirements,
      withQuestions,
      withDiagrams,
      enableExtraTools,
      maxPoints,
    },
    shouldSave: (v: any) => {
      return Boolean(
        String(v?.input || '').trim() ||
          String(v?.subject || '').trim() ||
          String(v?.requirements || '').trim() ||
          String(v?.preset || '').trim(),
      )
    },
    onRestore: (data: any) => {
      setInput(String(data?.input || ''))
      setSubject(String(data?.subject || ''))
      setPreset(toStudyMaterialsPreset(data?.preset))
      setRequirements(String(data?.requirements || ''))
      setWithQuestions((data?.withQuestions as TriState) || 'default')
      setWithDiagrams((data?.withDiagrams as TriState) || 'default')
      setEnableExtraTools((data?.enableExtraTools as TriState) || 'default')
      setMaxPoints(String(data?.maxPoints || ''))
    },
  })

  useEffect(() => {
    if (!reuseTaskId) return
    let active = true

    const toTriState = (v: unknown): TriState => {
      if (v === true) return 'on'
      if (v === false) return 'off'
      return 'default'
    }

    const run = async () => {
      try {
        const task = await tasksApi.getTask(reuseTaskId)
        if (!active) return
        const req = (task as any)?.request
        if (!req || typeof req !== 'object' || Array.isArray(req)) return

        // Start from a clean draft state.
        setCurrentConversation(null, 'study_materials')

        const query = String((req as any).query || '').trim()
        const subject = String((req as any).subject || '').trim()
        const options = (req as any).options && typeof (req as any).options === 'object' && !Array.isArray((req as any).options) ? (req as any).options : {}

        const presetRaw = String((options as any).preset || (req as any).preset || '').trim()
        const preset = toStudyMaterialsPreset(presetRaw)
        const requirements = String((options as any).requirements || (req as any).requirements || '').trim()

        setInput(query)
        setSubject(subject)
        setPreset(preset)
        setRequirements(requirements)

        setWithQuestions(toTriState((options as any).with_questions ?? (req as any).with_questions))
        setWithDiagrams(toTriState((options as any).with_diagrams ?? (req as any).with_diagrams))
        setEnableExtraTools(toTriState((options as any).enable_extra_tools ?? (req as any).enable_extra_tools))

        const mp = (options as any).max_points ?? (req as any).max_points
        setMaxPoints(mp != null ? String(mp) : '')
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
  }, [reuseTaskId])

  const messages = useConversationStore((state) =>
    state.getMessages(activeConversationId ?? '')
  )

  useEffect(() => {
    stick.maybeStick()
  }, [messages, stick.maybeStick])

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
      const text = await downloadText(mdUrl, { signal: controller.signal })
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
    if (!md || latexIsConverting || latexIsLoadingSource) return

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
          const env = normalizeSseEnvelope(data)
          const kind = env.type
          const payload = env.data as any

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

      const texText = await downloadText(texUrl, { signal: controller.signal })
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

        const env = normalizeSseEnvelope(data)
        const kind = env.type
        const payload = env.data as any
        const seq = env.seq
        if (Number.isFinite(seq)) recordSeq(seq as number)

        if (kind === 'task_started') {
          const taskId = toText(payload?.taskId) || toText(env.taskId)
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
          const perKpReport = (payload as any)?.per_kp_report

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

          const perKpLines: string[] = []
          if (Array.isArray(perKpReport) && perKpReport.length > 0) {
            perKpLines.push('---', '## 质量与成本报告', '')
            const missingLabels: Record<string, string> = {
              web_results_low: 'web 搜索结果偏少',
              web_pages_missing: '未抓取网页',
              llm_truncated: 'LLM 输出疑似截断',
              diagram_missing: '未生成示意图',
            }
            const toInt = (value: unknown): number => {
              const num = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
              if (!Number.isFinite(num)) return 0
              return Math.max(0, Math.floor(num))
            }
            for (const it of perKpReport) {
              const kp = toText((it as any)?.knowledge_point) || '（未命名）'
              const webResults = toInt((it as any)?.web_results)
              const webPages = toInt((it as any)?.web_pages)
              const ghResults = toInt((it as any)?.github_results)
              const seResults = toInt((it as any)?.stackexchange_results)
              const tokensTotal = toInt((it as any)?.tokens_total)
              const continuations = toInt((it as any)?.continuations)
              const missingRaw = (it as any)?.missing
              const missing = Array.isArray(missingRaw) ? missingRaw.map(toText).filter(Boolean) : []
              const missingText = missing.length > 0 ? missing.map((m) => missingLabels[m] || m).join('、') : '无'
              perKpLines.push(
                `- ${kp}：web_results=${webResults}, web_pages=${webPages}, github=${ghResults}, stackexchange=${seResults}, tokens=${tokensTotal}, continuations=${continuations}; missing=${missingText}`
              )
            }
          }

          const isExportFailure = ['convert_markdown_to_latex', 'refine_latex', 'compile_latex_to_pdf'].includes(fatalTool)
          const materialError =
            fatalTool || fatalMsg
              ? { tool: fatalTool || undefined, error: fatalMsg || undefined }
              : undefined
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
          if (perKpLines.length > 0) {
            content = [content, '', ...perKpLines].join('\n')
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
            ...(serverTaskId
              ? {
                  lastTask: {
                    taskType: 'study_materials',
                    taskId: serverTaskId,
                    lastSeq,
                    materialError,
                  },
                }
              : {}),
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

        const normalizedError = isApiError(err)
          ? new ApiError({
              code: err.code,
              message: formatStudyMaterialsError(err.message || '生成失败'),
              status: err.status,
              requestId: err.requestId,
              detail: err.detail,
              retriable: err.retriable,
              actions: err.actions,
            })
          : formatStudyMaterialsError((err as any)?.message || '生成失败')

        const msg = isApiError(normalizedError) ? normalizedError.message : String(normalizedError || '生成失败')
        setError(normalizedError)
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

  const handleSubmit = (e?: FormEvent) => {
    e?.preventDefault()
    const prompt = input.trim()
    if (!prompt || isGenerating) return
    stick.setShouldStick(true)

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

    clearDraft()

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
      stick.setShouldStick(true)

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

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const showSplitPane = hasSubAgentPane && !subAgentCollapsed

  const stopGenerating = useCallback(() => {
    abortActiveStream()
  }, [abortActiveStream])

  const resumeActiveStream = useCallback(() => {
    if (!activeConversationId) return
    if (!activeStreamTaskId || !activeStreamAssistantMessageId) return
    void resumeStudyMaterialsStreamWithProbe({
      conversationId: activeConversationId,
      assistantMessageId: activeStreamAssistantMessageId,
      taskId: activeStreamTaskId,
      afterSeq: Number(activeStreamLastSeq || 0),
    })
  }, [
    activeConversationId,
    activeStreamAssistantMessageId,
    activeStreamLastSeq,
    activeStreamTaskId,
    resumeStudyMaterialsStreamWithProbe,
  ])

  const discardResumableStream = useCallback(() => {
    if (!activeConversationId) return
    abortActiveStream()
    useConversationStore.getState().updateConversation(activeConversationId, {
      activeStream: undefined,
      resumable: false,
    })
  }, [abortActiveStream, activeConversationId])

  return {
    scrollRef,
    isNearBottom: stick.isNearBottom,
    scrollToBottom: () => {
      stick.scrollToBottom('smooth')
      stick.setShouldStick(true)
    },
    textareaRef,
    containerRef,
    input,
    setInput,
    isGeneratingLocal,
    isGenerating,
    error,
    clearError: () => setError(null),
    leftRatio,
    setLeftRatio,
    subAgentActivities,
    setSubAgentActivities,
    activeSubAgentTab,
    setActiveSubAgentTab,
    subAgentCollapsed,
    setSubAgentCollapsed,
    hasSubAgentPane,
    showSplitPane,
    optionsOpen,
    setOptionsOpen,
    subject,
    setSubject,
    preset,
    setPreset,
    requirements,
    setRequirements,
    withQuestions,
    setWithQuestions,
    withDiagrams,
    setWithDiagrams,
    enableExtraTools,
    setEnableExtraTools,
    maxPoints,
    setMaxPoints,
    latexDialogOpen,
    setLatexDialogOpen,
    latexLessonPlanId,
    setLatexLessonPlanId,
    latexFileName,
    setLatexFileName,
    latexTopic,
    setLatexTopic,
    latexSubject,
    setLatexSubject,
    latexMarkdown,
    setLatexMarkdown,
    latexIsConverting,
    setLatexIsConverting,
    latexError,
    setLatexError,
    latexIsLoadingSource,
    setLatexIsLoadingSource,
    latexProgressPercent,
    setLatexProgressPercent,
    latexProgressStage,
    setLatexProgressStage,
    latexTexUrl,
    setLatexTexUrl,
    latexTexFilename,
    setLatexTexFilename,
    latexTexText,
    setLatexTexText,
    latexNotice,
    setLatexNotice,
    conversations,
    currentConversationId,
    activeConversationId,
    activeConversation,
    messagesByConversation,
    messages,
    latexLessonPlanOptions,
    latexLessonPlanOptionById,
    hasResumableStream,
    isLastExportFailure,
    handleMessageScroll: stick.onScroll,
    abortActiveStream,
    stopGenerating,
    resumeActiveStream,
    discardResumableStream,
    openLatexDialog,
    handlePickLessonPlanMarkdown,
    clearLatexLessonPlanSelection,
    handleConvertToLatex,
    handleCopyLatex,
    handleDrag,
    handleNewConversation,
    handleSubmit,
    resumeStudyMaterialsStreamWithProbe,
    startContinueIteration,
    handleKeyDown,
  }
}

export type StudyMaterialsController = ReturnType<typeof useStudyMaterialsController>
