import { useCallback, useEffect, type MutableRefObject } from 'react'
import { getStudyMaterialsTask } from '@/api/studyMaterials'
import { useConversationStore } from '@/stores/useConversationStore'
import type { RunStudyMaterialsStreamOptions } from '@/features/studyMaterials/hooks/useStudyMaterialsStreamRunner'

type ActiveStreamState = {
  taskId?: string
  assistantMessageId?: string
  lastSeq?: number
}

export function useStudyMaterialsResumableStream(opts: {
  activeConversationId: string | null
  activeStream: ActiveStreamState | undefined
  isStreaming: boolean
  streamKeyRef: MutableRefObject<string | null>
  runStudyMaterialsStream: (opts: RunStudyMaterialsStreamOptions) => void
  abortActiveStream: () => void
  setError: (err: unknown) => void
}) {
  const { activeConversationId, activeStream, isStreaming, streamKeyRef, runStudyMaterialsStream, abortActiveStream, setError } = opts

  const resumeStudyMaterialsStreamWithProbe = useCallback(
    async (resumeOpts: {
      conversationId: string
      assistantMessageId: string
      taskId: string
      afterSeq: number
    }) => {
      const conversationId = resumeOpts.conversationId
      const assistantMessageId = resumeOpts.assistantMessageId
      const taskId = String(resumeOpts.taskId || '').trim()
      const afterSeq = Number.isFinite(resumeOpts.afterSeq) ? resumeOpts.afterSeq : 0

      if (!taskId) return
      if (isStreaming) return

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
        setError('任务已丢失（可能是本地服务重启或任务过期）。请重新生成。')
        return
      }

      runStudyMaterialsStream({
        conversationId,
        assistantMessageId,
        request: {
          url: `/tasks/${encodeURIComponent(taskId)}/stream?after_seq=${afterSeq}`,
          method: 'GET',
        },
        initialTaskId: taskId,
        initialSeq: afterSeq,
        streamKey: `${conversationId}:${taskId}`,
      })
    },
    [isStreaming, runStudyMaterialsStream, setError]
  )

  const activeStreamTaskId = String(activeStream?.taskId || '').trim()
  const activeStreamAssistantMessageId = String(activeStream?.assistantMessageId || '').trim()
  const activeStreamLastSeq = Number(activeStream?.lastSeq || 0)

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
    activeStreamAssistantMessageId,
    activeStreamLastSeq,
    activeStreamTaskId,
    resumeStudyMaterialsStreamWithProbe,
    streamKeyRef,
  ])

  useEffect(() => {
    return () => {
      abortActiveStream()
    }
  }, [abortActiveStream])

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
    resumeStudyMaterialsStreamWithProbe,
    stopGenerating,
    resumeActiveStream,
    discardResumableStream,
  }
}

