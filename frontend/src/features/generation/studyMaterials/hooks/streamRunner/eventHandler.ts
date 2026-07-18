import { useConversationStore } from '@/stores/useConversationStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { generateId } from '@/lib/utils'
import { formatStudyMaterialsError, normalizeKnowledgePoints, toText } from '@/features/generation/studyMaterials/utils'
import { toRecord, toTaskStepStatus } from '@/features/generation/studyMaterials/hooks/streamRunner/streamUtils'
import type { AssistantMessageTracker } from '@/features/generation/studyMaterials/hooks/streamRunner/assistantMessageTracker'
import type { SubAgentTracker } from '@/features/generation/studyMaterials/hooks/streamRunner/subAgentTracker'
import type { TaskStep } from '@/types'

export type StreamEventHandlerContext = {
  conversationId: string
  assistantMessageId: string
  localTaskId?: string
  /** Mutable session state shared with the stream session. */
  state: {
    serverTaskId: string | null
    lastSeq: number
    done: boolean
    recovery?: {
      stage?: string
      recoverable: boolean
    }
  }
  assistant: AssistantMessageTracker
  subAgents: SubAgentTracker
  setIsGeneratingLocal: (next: boolean) => void
  setError: (next: unknown) => void
}

const getPayloadInput = (payload: Record<string, unknown>) => payload.input ?? payload.arguments

/**
 * Builds the per-session stream event handler. The returned function consumes a
 * normalized SSE envelope and applies the resulting mutations to the conversation
 * store, task store and the assistant/subagent trackers.
 */
export function createStreamEventHandler(ctx: StreamEventHandlerContext) {
  const {
    conversationId,
    assistantMessageId,
    localTaskId,
    state,
    assistant,
    subAgents,
    setIsGeneratingLocal,
    setError,
  } = ctx

  const markResumable = () => {
    if (!state.serverTaskId) return
    useConversationStore.getState().updateConversation(conversationId, {
      activeStream: { taskType: 'study_materials', taskId: state.serverTaskId, assistantMessageId, lastSeq: state.lastSeq },
      resumable: true,
    })
  }

  return function handleStreamEvent(env: unknown) {
    const envelope = toRecord(env)
    const kind = toText(envelope.type).trim()
    const payload = toRecord(envelope.data)

    if (kind === 'ping') {
      // Keep the conversation marked as resumable while running.
      markResumable()
      return
    }

    if (kind === 'task_started') {
      const tid = toText(payload?.taskId)
      if (tid) state.serverTaskId = tid
      setIsGeneratingLocal(true)
      markResumable()
      return
    }

    if (kind === 'text_delta') {
      const text = toText(payload?.content)
      if (text) {
        assistant.appendText(text)
      }
      return
    }

    if (kind === 'tool_start' || kind === 'tool_call') {
      const toolName = toText(payload?.tool) || toText(payload?.name)
      const title = toText(payload?.title) || toolName || '工具调用'
      const thought = toText(payload?.thought) || undefined
      const stepId = toText(payload?.step_id) || generateId()
      const input = getPayloadInput(payload)
      const step: TaskStep = {
        id: stepId,
        title,
        thought,
        status: 'running',
        startTime: toText(payload?.start_time) || new Date().toISOString(),
        toolName: toolName || undefined,
        input,
      }
      assistant.upsertStep(step)

      const kp = subAgents.getPayloadKnowledgePoint(payload, stepId)
      if (kp) {
        subAgents.startSubAgent(kp)
        subAgents.registerStepKP(stepId, kp)
        if (kind === 'tool_call') {
          subAgents.upsertSubAgentStep(kp, step)
        } else {
          subAgents.startSubAgentThinking(kp, toolName)
        }
      } else {
        assistant.createThinkingStepIfNeeded(toolName)
      }
      return
    }

    if (kind === 'tool_delta' || kind === 'thinking') {
      const text = toText(payload?.content)
      if (text) {
        const kp = subAgents.getPayloadKnowledgePoint(payload) || subAgents.getSoleActiveSubAgent()
        if (kp) {
          subAgents.startSubAgentThinking(kp, 'thinking')
          subAgents.appendSubAgentThinking(kp, text)
        } else {
          assistant.createThinkingStepIfNeeded('thinking')
          assistant.appendThinking(text)
        }
      }
      return
    }

    if (kind === 'tool_end' || kind === 'tool_result') {
      const stepId = toText(payload?.step_id)
      const status = toTaskStepStatus(
        toText(payload.status) || (payload.success === false ? 'failed' : 'completed'),
        'completed'
      )
      const endTime = toText(payload?.end_time) || new Date().toISOString()
      const output = payload?.output ?? payload?.result
      const error = toText(payload?.error || payload?.message) || undefined
      const toolName = toText(payload?.tool) || toText(payload?.name)

      if (stepId) {
        assistant.patchStep(stepId, { status, endTime, output, error })
      }

      const kp = subAgents.getPayloadKnowledgePoint(payload, stepId || undefined)
      if (kp && stepId) {
        subAgents.patchSubAgentStep(kp, stepId, {
          status,
          endTime,
          output,
          error,
          toolName: toolName || undefined,
        })
        subAgents.completeSubAgentThinking(kp)
        if (status === 'failed') {
          subAgents.updateSubAgentStatus(kp)
        } else if (!subAgents.hasActiveSubAgent(kp)) {
          subAgents.updateSubAgentStatus(kp)
        }
      }

      const kps = normalizeKnowledgePoints(toRecord(output).knowledge_points)
      if ((toolName === 'split_knowledge_points' || toolName === 'review_knowledge_points') && kps.length > 0) {
        subAgents.initializeSubAgentActivities(kps)
      } else if (kind === 'tool_end' && kps.length === 1) {
        subAgents.endSubAgent(kps[0])
      } else if (!kp) {
        assistant.completeThinkingStep()
      }
      return
    }

    if (kind === 'subagent_start') {
      const kp = toText(payload?.knowledge_point || payload?.knowledgePoint)
      if (kp) subAgents.startSubAgent(kp)
      return
    }

    if (kind === 'subagent_end') {
      const kp = toText(payload?.knowledge_point || payload?.knowledgePoint)
      if (kp) subAgents.endSubAgent(kp)
      return
    }

    if (kind === 'step') {
      const rawStep = payload.step
      if (rawStep && typeof rawStep === 'object' && !Array.isArray(rawStep)) {
        const step = toRecord(rawStep)
        const stepId = toText(step.id) || generateId()
        const status = toTaskStepStatus(step.status, 'running')
        assistant.upsertStep({
          id: stepId,
          title: toText(step.title) || '步骤',
          thought: toText(step.thought) || undefined,
          status,
          startTime: toText(step.startTime) || undefined,
          endTime: toText(step.endTime) || undefined,
          toolName: toText(step.toolName) || undefined,
          input: step.input,
          output: step.output,
          error: toText(step.error) || undefined,
        })
      }
      return
    }

    if (kind === 'result') {
      // Some workflows emit a final result payload.
      return
    }

    if (kind === 'recovery_available') {
      const stage = toText(payload.stage).trim() || undefined
      const recoverable = payload.recoverable !== false
      state.recovery = { stage, recoverable }
      if (state.serverTaskId) {
        useConversationStore.getState().updateConversation(conversationId, {
          resumable: recoverable,
          lastTask: {
            taskType: 'study_materials',
            taskId: state.serverTaskId,
            lastSeq: state.lastSeq,
            recovery: state.recovery,
          },
        })
      }
      return
    }

    if (kind === 'done') {
      state.done = true
      assistant.flushAssistant()
      if (state.serverTaskId) {
        const material = toRecord(payload.material ?? toRecord(payload.result).material)
        const rawError = toRecord(material.error)
        const materialErrorTool = toText(rawError.tool)
        const materialErrorText = toText(rawError.error)
        useConversationStore.getState().updateConversation(conversationId, {
          activeStream: undefined,
          resumable: false,
          status: 'completed',
          lastTask: {
            taskType: 'study_materials',
            taskId: state.serverTaskId,
            lastSeq: state.lastSeq,
            materialError:
              materialErrorTool || materialErrorText
                ? { tool: materialErrorTool || undefined, error: materialErrorText || undefined }
                : undefined,
          },
        })
      }
      setIsGeneratingLocal(false)
      if (localTaskId) {
        useTaskStore.getState().completeTask(localTaskId)
      }
      return
    }

    if (kind === 'error') {
      const msg = formatStudyMaterialsError(toText(payload?.message) || toText(payload?.error) || '生成失败')
      if (msg) setError(msg)
      state.done = true
      assistant.flushAssistant()
      setIsGeneratingLocal(false)
      if (localTaskId) {
        useTaskStore.getState().failTask(localTaskId, msg)
      }
      if (state.serverTaskId) {
        const payloadStage = toText(payload.stage).trim()
        const recovery = payloadStage
          ? { stage: payloadStage, recoverable: payload.recoverable !== false }
          : state.recovery
        useConversationStore.getState().updateConversation(conversationId, {
          activeStream: undefined,
          resumable: recovery?.recoverable === true,
          status: 'failed',
          lastTask: {
            taskType: 'study_materials',
            taskId: state.serverTaskId,
            lastSeq: state.lastSeq,
            recovery,
          },
        })
      }
    }
  }
}
