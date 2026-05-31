import { useConversationStore } from '@/stores/useConversationStore'
import { appendCappedText, mergeAndSanitizeTaskStep, sanitizeTaskStep, sanitizeTaskSteps } from '@/lib/taskPayload'
import { generateId } from '@/lib/utils'
import type { TaskStep } from '@/types'

type AssistantMessageTrackerDeps = {
  conversationId: string
  assistantMessageId: string
}

/**
 * Tracks the main assistant message text, step list and the streaming "thinking"
 * panel for a single study-materials stream session.
 */
export function createAssistantMessageTracker({ conversationId, assistantMessageId }: AssistantMessageTrackerDeps) {
  const existing = useConversationStore
    .getState()
    .getMessages(conversationId)
    .find((m) => m.id === assistantMessageId)

  let assistantSteps: TaskStep[] = Array.isArray(existing?.steps) ? (existing?.steps as TaskStep[]) : []
  let assistantText = typeof existing?.content === 'string' ? existing!.content : ''
  let pendingText = ''
  let flushTimer: number | null = null

  // Streaming "thinking" panel (auto-expanded while running, auto-collapsed when finished).
  let thinkingStepId: string | null = null
  let thinkingStartTime: string | null = null
  let thinkingBuffer = ''

  const flushAssistant = () => {
    if (flushTimer) {
      window.clearTimeout(flushTimer)
      flushTimer = null
    }

    const nextText = assistantText + pendingText
    if (!pendingText) return
    assistantText = nextText
    pendingText = ''

    useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
      content: assistantText,
      steps: assistantSteps,
    })
  }

  const scheduleFlush = () => {
    if (flushTimer) return
    flushTimer = window.setTimeout(() => flushAssistant(), 80)
  }

  const appendText = (text: string) => {
    pendingText += text
    scheduleFlush()
  }

  const upsertStep = (step: TaskStep) => {
    const sanitizedStep = sanitizeTaskStep(step)
    const hasStep = assistantSteps.some((s) => s.id === sanitizedStep.id)
    assistantSteps = sanitizeTaskSteps(
      hasStep
        ? assistantSteps.map((s) => (s.id === sanitizedStep.id ? mergeAndSanitizeTaskStep(s, sanitizedStep) : s))
        : [...assistantSteps, sanitizedStep]
    )

    useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
      content: assistantText + pendingText,
      steps: assistantSteps,
    })
  }

  const patchStep = (stepId: string, patch: Partial<TaskStep>) => {
    const hasStep = assistantSteps.some((s) => s.id === stepId)
    if (!hasStep) {
      upsertStep({
        id: stepId,
        title: patch.title || patch.toolName || '步骤',
        status: patch.status || 'running',
        startTime: patch.startTime,
        endTime: patch.endTime,
        toolName: patch.toolName,
        input: patch.input,
        output: patch.output,
        error: patch.error,
      })
      return
    }
    assistantSteps = sanitizeTaskSteps(assistantSteps.map((s) => (s.id === stepId ? mergeAndSanitizeTaskStep(s, patch) : s)))
    useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
      content: assistantText + pendingText,
      steps: assistantSteps,
    })
  }

  const createThinkingStepIfNeeded = (toolName: string) => {
    if (thinkingStepId) return
    thinkingStepId = generateId()
    thinkingStartTime = new Date().toISOString()
    thinkingBuffer = ''
    upsertStep({
      id: thinkingStepId,
      title: `思考中：${toolName || '任务'}`,
      status: 'running',
      startTime: thinkingStartTime,
      toolName: toolName || undefined,
      input: undefined,
      output: '',
    })
  }

  const appendThinking = (text: string) => {
    if (!thinkingStepId) return
    thinkingBuffer = appendCappedText(thinkingBuffer, text || '', 12000)
    patchStep(thinkingStepId, { output: thinkingBuffer })
  }

  const completeThinkingStep = () => {
    if (!thinkingStepId) return
    patchStep(thinkingStepId, { status: 'completed', endTime: new Date().toISOString() })
    thinkingStepId = null
    thinkingStartTime = null
    thinkingBuffer = ''
  }

  const writeErrorContent = (msg: string) => {
    useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
      content: `出错：${msg}`,
      steps: assistantSteps,
    })
  }

  return {
    flushAssistant,
    appendText,
    upsertStep,
    patchStep,
    createThinkingStepIfNeeded,
    appendThinking,
    completeThinkingStep,
    writeErrorContent,
  }
}

export type AssistantMessageTracker = ReturnType<typeof createAssistantMessageTracker>
