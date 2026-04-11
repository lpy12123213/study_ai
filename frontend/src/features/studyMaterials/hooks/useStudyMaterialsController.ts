import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { apiClient } from '@/api/client'
import { getStudyMaterialsTask, type StudyMaterialsTaskStatus } from '@/api/studyMaterials'
import { useStickToBottom } from '@/hooks/useStickToBottom'
import { useAuthStore } from '@/stores/useAuthStore'
import { useConversationStore } from '@/stores/useConversationStore'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { generateId } from '@/lib/utils'
import { useStudyMaterialsDraftOptions } from '@/features/studyMaterials/hooks/useStudyMaterialsDraftOptions'
import { useStudyMaterialsLatexExport } from '@/features/studyMaterials/hooks/useStudyMaterialsLatexExport'
import { useStudyMaterialsSubAgentPane } from '@/features/studyMaterials/hooks/useStudyMaterialsSubAgentPane'
import { useStudyMaterialsResumableStream } from '@/features/studyMaterials/hooks/useStudyMaterialsResumableStream'
import { useStudyMaterialsStreamRunner } from '@/features/studyMaterials/hooks/useStudyMaterialsStreamRunner'
import {
  toConversationTitle,
  toText,
  formatStudyMaterialsError,
} from '@/features/studyMaterials/utils'
import type { ConversationItem } from '@/types'
import type { TriState } from '@/features/studyMaterials/types'

export function useStudyMaterialsController() {
  const stick = useStickToBottom({ thresholdPx: 120 })
  const scrollRef = stick.containerRef
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const prevConversationIdRef = useRef<string | null>(null)
  const userId = useAuthStore((s) => s.user?.id || '')
  const [searchParams, setSearchParams] = useSearchParams()
  const reuseTaskId = String(searchParams.get('reuse_task') || '').trim()

  const [isGeneratingLocal, setIsGeneratingLocal] = useState(false)
  const [error, setError] = useState<unknown>(null)

  // Split pane: left panel width ratio (0.25 to 0.75)
  const [leftRatio, setLeftRatio] = useState(0.38)

  const conversations = useConversationStore((state) => state.conversations)
  const currentConversationId = useConversationStore((state) => state.currentConversationIdByType.study_materials)
  const addConversation = useConversationStore((state) => state.addConversation)
  const setCurrentConversation = useConversationStore((state) => state.setCurrentConversation)
  const updateConversation = useConversationStore((state) => state.updateConversation)
  const setMessages = useConversationStore((state) => state.setMessages)
  const addMessage = useConversationStore((state) => state.addMessage)

  const messagesByConversation = useConversationStore((state) => state.messagesByConversation)

  const lessonPlansById = useLessonPlanStore((state) => state.plansById)

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

  const {
    input,
    setInput,
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
    clearDraft,
  } = useStudyMaterialsDraftOptions({
    userId,
    activeConversationId,
    isGenerating: isGeneratingLocal,
    reuseTaskId,
    searchParams,
    setSearchParams,
    setCurrentConversation,
  })

  const {
    subAgentActivities,
    setSubAgentActivities,
    activeSubAgentTab,
    setActiveSubAgentTab,
    subAgentCollapsed,
    setSubAgentCollapsed,
    hasSubAgentPane,
  } = useStudyMaterialsSubAgentPane({
    activeConversationId,
    isStreaming: isGeneratingLocal,
  })

  const { abortActiveStream, runStudyMaterialsStream, streamKeyRef } = useStudyMaterialsStreamRunner({
    setIsGeneratingLocal,
    setError,
    setSubAgentActivities,
    setActiveSubAgentTab,
  })

  const { resumeStudyMaterialsStreamWithProbe, stopGenerating, resumeActiveStream, discardResumableStream } =
    useStudyMaterialsResumableStream({
      activeConversationId,
      activeStream,
      isStreaming: isGeneratingLocal,
      streamKeyRef,
      runStudyMaterialsStream,
      abortActiveStream,
      setError,
    })

  const latex = useStudyMaterialsLatexExport({
    defaultSubject: subject.trim() || '高中数学',
    lessonPlansById,
    conversations,
    messagesByConversation,
  })

  const [lastTaskStatus, setLastTaskStatus] = useState<StudyMaterialsTaskStatus | null>(null)
  const [lastTaskStatusError, setLastTaskStatusError] = useState<string | null>(null)

  useEffect(() => {
    const taskId = String(activeConversation?.lastTask?.taskId || '').trim()
    if (!taskId || activeConversation?.status !== 'failed') {
      setLastTaskStatus(null)
      setLastTaskStatusError(null)
      return
    }

    let active = true
    setLastTaskStatusError(null)

    void (async () => {
      try {
        const status = await getStudyMaterialsTask(taskId)
        if (!active) return
        setLastTaskStatus(status)
      } catch (err: any) {
        if (!active) return
        setLastTaskStatus(null)
        setLastTaskStatusError(toText(err?.message) || '任务状态获取失败')
      }
    })()

    return () => {
      active = false
    }
  }, [activeConversation?.lastTask?.taskId, activeConversation?.status])

  const messages = useConversationStore((state) =>
    state.getMessages(activeConversationId ?? '')
  )

  useEffect(() => {
    stick.maybeStick()
  }, [messages, stick.maybeStick])

  // Sidebar "new conversation" clears the current conversation selection but does not reset
  // page-local React state. Reset here so the UI is actually clean.
  useEffect(() => {
    const prev = prevConversationIdRef.current
    prevConversationIdRef.current = activeConversationId

    // On initial mount, keep drafts (useFormDraft) intact.
    if (activeConversationId) return
    if (!prev) return

    abortActiveStream()
    setInput('')
    setError(null)
  }, [abortActiveStream, activeConversationId, setInput])

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

    void apiClient
      .post('/tasks/study-materials/generate', body)
      .then((res) => {
        const taskId = String((res.data as any)?.taskId || '').trim()
        if (!taskId) throw new Error('missing_task_id')

        useTaskStore.getState().startTask(taskId)
        runStudyMaterialsStream({
          conversationId,
          assistantMessageId,
          request: {
            url: `/tasks/${encodeURIComponent(taskId)}/stream?after_seq=0`,
            method: 'GET',
          },
          localTaskId: taskId,
          initialTaskId: taskId,
          initialSeq: 0,
          streamKey: `${conversationId}:${taskId}`,
        })
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : '生成失败'
        setError(formatStudyMaterialsError(msg))
        useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
          content: `出错：${msg}`,
          steps: [],
        })
        updateConversation(conversationId, { updatedAt: new Date().toISOString(), status: 'active' })
      })
  }

  const startContinueIteration = useCallback(
    (
      mode:
        | 'improve'
        | 'deepen_research'
        | 'fix_export'
        | 'skip_export'
        | 'resume_failed_stage'
        | 'retry_search'
        | 'replan_from_failure'
    ) => {
      if (!activeConversationId) return
      const baseTaskId = String(lastTask?.taskId || '').trim()
      if (!baseTaskId) return
      if (isGenerating) return
      stick.setShouldStick(true)

      const now = new Date().toISOString()
      const userText =
        mode === 'retry_search'
          ? '继续：重试检索（仅重跑检索阶段）'
          : mode === 'resume_failed_stage'
            ? '继续：从失败阶段继续'
            : mode === 'replan_from_failure'
              ? '继续：重新规划并续跑'
              : mode === 'deepen_research'
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

      void apiClient
        .post(`/tasks/study-materials/${encodeURIComponent(baseTaskId)}/continue`, { mode })
        .then((res) => {
          const taskId = String((res.data as any)?.taskId || '').trim()
          if (!taskId) throw new Error('missing_task_id')

          useTaskStore.getState().startTask(taskId)
          runStudyMaterialsStream({
            conversationId: activeConversationId,
            assistantMessageId,
            request: {
              url: `/tasks/${encodeURIComponent(taskId)}/stream?after_seq=0`,
              method: 'GET',
            },
            localTaskId: taskId,
            initialTaskId: taskId,
            initialSeq: 0,
            streamKey: `${activeConversationId}:${taskId}`,
          })
        })
        .catch((err: unknown) => {
          const msg = err instanceof Error ? err.message : '继续失败'
          setError(formatStudyMaterialsError(msg))
          useConversationStore.getState().updateMessage(activeConversationId, assistantMessageId, {
            content: `出错：${msg}`,
            steps: [],
          })
          updateConversation(activeConversationId, { updatedAt: new Date().toISOString(), status: 'active' })
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
    ...latex,
    conversations,
    currentConversationId,
    activeConversationId,
    activeConversation,
    lastTaskStatus,
    lastTaskStatusError,
    messagesByConversation,
    messages,
    hasResumableStream,
    isLastExportFailure,
    handleMessageScroll: stick.onScroll,
    abortActiveStream,
    stopGenerating,
    resumeActiveStream,
    discardResumableStream,
    handleDrag,
    handleNewConversation,
    handleSubmit,
    resumeStudyMaterialsStreamWithProbe,
    startContinueIteration,
    handleKeyDown,
  }
}

export type StudyMaterialsController = ReturnType<typeof useStudyMaterialsController>
