import {
  useCallback,
  useEffect,
  useRef,
  type Dispatch,
  type FormEvent,
  type KeyboardEvent,
  type SetStateAction,
} from 'react'
import type { useStickToBottom } from '@/hooks/useStickToBottom'
import { useConversationStore } from '@/stores/useConversationStore'
import { shouldSubmitOnEnter } from '@/lib/keyboard'
import { generateId } from '@/lib/utils'
import { toConversationTitle } from '@/features/generation/studyMaterials/utils'
import { useSplitPaneRatio } from '@/features/generation/studyMaterials/hooks/useSplitPaneRatio'
import {
  beginAssistantTurn,
  ensureStudyMaterialsConversation,
} from '@/features/generation/studyMaterials/hooks/conversationTurn'
import {
  buildGenerateBody,
  continueIterationUserText,
  launchStudyMaterialsTask,
  type ContinueIterationMode,
} from '@/features/generation/studyMaterials/hooks/studyMaterialsTaskLaunch'
import type { RunStudyMaterialsStreamOptions } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsStreamRunner'
import type { ConversationItem } from '@/types'
import type { SubAgentActivity, TriState } from '@/features/generation/studyMaterials/types'

type StickToBottom = ReturnType<typeof useStickToBottom>

type ActiveStreamState = ConversationItem['activeStream']
type LastTaskState = ConversationItem['lastTask']

export type { ContinueIterationMode }

export interface UseStudyMaterialsActionsParams {
  stick: StickToBottom
  activeConversationId: string | null
  activeStream: ActiveStreamState
  lastTask: LastTaskState
  isGenerating: boolean
  // Draft options
  input: string
  setInput: (next: string) => void
  clearDraft: () => void
  subject: string
  preset: string
  requirements: string
  withQuestions: TriState
  withDiagrams: TriState
  enableExtraTools: TriState
  maxPoints: string
  // SubAgent pane setters
  setSubAgentActivities: Dispatch<SetStateAction<SubAgentActivity[]>>
  setActiveSubAgentTab: Dispatch<SetStateAction<string | null>>
  // Stream runner
  runStudyMaterialsStream: (opts: RunStudyMaterialsStreamOptions) => void
  abortActiveStream: () => void
  resumeStudyMaterialsStreamWithProbe: (opts: {
    conversationId: string
    assistantMessageId: string
    taskId: string
    afterSeq: number
  }) => Promise<void> | void
  setError: (next: unknown) => void
}

const CONTINUE_INTENTS = new Set(['继续', '接着', '续写', '继续生成', '继续输出', 'continue', 'resume'])

/**
 * Encapsulates the imperative study-materials actions: split-pane dragging,
 * starting/continuing/resuming generations and keyboard submission.
 */
export function useStudyMaterialsActions(params: UseStudyMaterialsActionsParams) {
  const {
    stick,
    activeConversationId,
    activeStream,
    lastTask,
    isGenerating,
    input,
    setInput,
    clearDraft,
    subject,
    preset,
    requirements,
    withQuestions,
    withDiagrams,
    enableExtraTools,
    maxPoints,
    setSubAgentActivities,
    setActiveSubAgentTab,
    runStudyMaterialsStream,
    abortActiveStream,
    resumeStudyMaterialsStreamWithProbe,
    setError,
  } = params

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const prevConversationIdRef = useRef<string | null>(null)

  // Split pane: left panel width ratio (0.25 to 0.75)
  const { containerRef, leftRatio, setLeftRatio, handleDrag } = useSplitPaneRatio(0.38)

  const addConversation = useConversationStore((state) => state.addConversation)
  const setCurrentConversation = useConversationStore((state) => state.setCurrentConversation)
  const updateConversation = useConversationStore((state) => state.updateConversation)
  const setMessages = useConversationStore((state) => state.setMessages)
  const addMessage = useConversationStore((state) => state.addMessage)

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
  }, [abortActiveStream, activeConversationId, setInput, setError])

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
    const isContinueIntent = CONTINUE_INTENTS.has(normalized)

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
    setInput('')

    const conversationId = ensureStudyMaterialsConversation({
      activeConversationId,
      title: toConversationTitle(prompt),
      now,
      addConversation,
      setCurrentConversation,
      setMessages,
      updateConversation,
    })

    const assistantMessageId = beginAssistantTurn({
      conversationId,
      userText: prompt,
      now,
      addMessage,
      setError,
      setSubAgentActivities,
      setActiveSubAgentTab,
    })

    const body = buildGenerateBody({
      prompt,
      subject,
      preset,
      requirements,
      withQuestions,
      withDiagrams,
      enableExtraTools,
      maxPoints,
    })

    launchStudyMaterialsTask({
      endpoint: '/tasks/study-materials/generate',
      body,
      conversationId,
      assistantMessageId,
      fallbackErrorMessage: '生成失败',
      runStudyMaterialsStream,
      updateConversation,
      setError,
    })
  }

  const startContinueIteration = useCallback(
    (mode: ContinueIterationMode) => {
      if (!activeConversationId) return
      const baseTaskId = String(lastTask?.taskId || '').trim()
      if (!baseTaskId) return
      if (isGenerating) return
      stick.setShouldStick(true)

      const now = new Date().toISOString()
      const assistantMessageId = beginAssistantTurn({
        conversationId: activeConversationId,
        userText: continueIterationUserText(mode),
        now,
        addMessage,
        setError,
        setSubAgentActivities,
        setActiveSubAgentTab,
      })

      updateConversation(activeConversationId, {
        updatedAt: now,
        status: 'active',
        progress: 0,
        activeStream: undefined,
        resumable: false,
      })

      launchStudyMaterialsTask({
        endpoint: `/tasks/study-materials/${encodeURIComponent(baseTaskId)}/continue`,
        body: { mode },
        conversationId: activeConversationId,
        assistantMessageId,
        fallbackErrorMessage: '继续失败',
        runStudyMaterialsStream,
        updateConversation,
        setError,
      })
    },
    [
      activeConversationId,
      lastTask?.taskId,
      isGenerating,
      stick,
      addMessage,
      setError,
      setSubAgentActivities,
      setActiveSubAgentTab,
      updateConversation,
      runStudyMaterialsStream,
    ]
  )

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (shouldSubmitOnEnter(e)) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return {
    textareaRef,
    containerRef,
    leftRatio,
    setLeftRatio,
    handleDrag,
    handleNewConversation,
    handleSubmit,
    startContinueIteration,
    handleKeyDown,
  }
}
