import { ApiError, fetchSSERequest, isApiError } from '@/api/client'
import { streamTaskWs } from '@/api/ws'
import { useConversationStore } from '@/stores/useConversationStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { normalizeSseEnvelope } from '@/lib/sse'
import { formatStudyMaterialsError, toText } from '@/features/generation/studyMaterials/utils'
import { parseTaskStreamUrl, toRecord } from '@/features/generation/studyMaterials/hooks/streamRunner/streamUtils'
import type { AssistantMessageTracker } from '@/features/generation/studyMaterials/hooks/streamRunner/assistantMessageTracker'
import type { StudyMaterialsStreamRequest } from '@/features/generation/studyMaterials/hooks/streamRunner/types'

export type StreamConnectionContext = {
  conversationId: string
  assistantMessageId: string
  localTaskId?: string
  request: StudyMaterialsStreamRequest
  controller: AbortController
  state: {
    serverTaskId: string | null
    lastSeq: number
    done: boolean
  }
  assistant: AssistantMessageTracker
  handleStreamEvent: (env: unknown) => void
  setIsGeneratingLocal: (next: boolean) => void
  setError: (next: unknown) => void
  /** Returns true when this controller is still the active stream controller. */
  isActiveController: () => boolean
  /** Clears the active stream controller ref when the connection finishes. */
  onComplete: () => void
}

/**
 * Opens the actual transport (WebSocket for canonical task streams, SSE otherwise)
 * and wires the data/error/complete callbacks to the session trackers.
 */
export function openStreamConnection(ctx: StreamConnectionContext) {
  const {
    conversationId,
    assistantMessageId,
    localTaskId,
    request,
    controller,
    state,
    assistant,
    handleStreamEvent,
    setIsGeneratingLocal,
    setError,
    isActiveController,
    onComplete,
  } = ctx

  const handleStreamData = (data: unknown) => {
    const env = normalizeSseEnvelope(data)
    const seq = typeof env.seq === 'number' ? env.seq : Number(env.seq || 0)
    if (Number.isFinite(seq) && seq > state.lastSeq) state.lastSeq = seq
    if (state.serverTaskId) {
      useConversationStore.getState().updateConversation(conversationId, {
        activeStream: { taskType: 'study_materials', taskId: state.serverTaskId, assistantMessageId, lastSeq: state.lastSeq },
        resumable: true,
      })
    }
    handleStreamEvent(env)
  }

  const handleStreamError = (err: unknown) => {
    const normalizedError =
      err instanceof ApiError
        ? err
        : isApiError(err)
          ? new ApiError({
              code: err.code,
              message: formatStudyMaterialsError(err.message || '生成失败'),
              status: err.status,
              requestId: err.requestId,
              detail: err.detail,
              retriable: err.retriable,
              actions: err.actions,
            })
          : formatStudyMaterialsError(err instanceof Error ? err.message : toText(toRecord(err).message) || '生成失败')

    const msg = isApiError(normalizedError) ? normalizedError.message : String(normalizedError || '生成失败')
    setError(normalizedError)
    if (localTaskId) {
      useTaskStore.getState().failTask(localTaskId, msg)
    }
    assistant.writeErrorContent(msg)
    // Keep activeStream so the user can refresh/reconnect.
    setIsGeneratingLocal(false)
  }

  const handleStreamComplete = () => {
    if (!isActiveController()) return
    if (!state.done) {
      // Connection closed unexpectedly: keep the task resumable.
      setIsGeneratingLocal(false)
    }
    onComplete()
  }

  // Use WebSocket for the unified task stream (`GET /tasks/{id}/stream?after_seq=N`).
  // This avoids SSE timeouts during long-running studies and gives durable
  // refresh-resume via the persistent connection.
  const taskStream = parseTaskStreamUrl(request.url, request.method)
  if (taskStream) {
    if (taskStream.taskId) state.serverTaskId = taskStream.taskId
    const cleanup = streamTaskWs(
      taskStream.taskId,
      taskStream.afterSeq,
      handleStreamData,
      handleStreamError,
      handleStreamComplete,
      { signal: controller.signal },
    )
    // Wire abort to cleanup the WS connection.
    if (controller.signal.aborted) {
      cleanup()
    } else {
      controller.signal.addEventListener('abort', () => cleanup())
    }
    return
  }

  void fetchSSERequest(
    request.url,
    { method: request.method, body: request.body, signal: controller.signal, inactivityTimeoutMs: 120_000 },
    handleStreamData,
    handleStreamError,
    handleStreamComplete,
  )
}
