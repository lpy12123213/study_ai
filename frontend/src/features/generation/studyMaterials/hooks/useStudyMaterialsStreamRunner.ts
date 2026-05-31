import { useCallback, useRef } from 'react'
import { createAssistantMessageTracker } from '@/features/generation/studyMaterials/hooks/streamRunner/assistantMessageTracker'
import { createSubAgentTracker } from '@/features/generation/studyMaterials/hooks/streamRunner/subAgentTracker'
import { createStreamEventHandler } from '@/features/generation/studyMaterials/hooks/streamRunner/eventHandler'
import { openStreamConnection } from '@/features/generation/studyMaterials/hooks/streamRunner/streamConnection'
import type {
  RunStudyMaterialsStreamOptions,
  StudyMaterialsStreamCallbacks,
} from '@/features/generation/studyMaterials/hooks/streamRunner/types'

export type {
  StudyMaterialsStreamRequest,
  RunStudyMaterialsStreamOptions,
} from '@/features/generation/studyMaterials/hooks/streamRunner/types'

export function useStudyMaterialsStreamRunner(opts: StudyMaterialsStreamCallbacks) {
  const { setIsGeneratingLocal, setError, setSubAgentActivities, setActiveSubAgentTab } = opts

  const streamAbortRef = useRef<AbortController | null>(null)
  const streamKeyRef = useRef<string | null>(null)

  const abortActiveStream = useCallback(() => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort()
      streamAbortRef.current = null
    }
    streamKeyRef.current = null
    setIsGeneratingLocal(false)
  }, [setIsGeneratingLocal])

  const runStudyMaterialsStream = useCallback(
    (runOpts: RunStudyMaterialsStreamOptions) => {
      const { conversationId, assistantMessageId, request, localTaskId } = runOpts
      const controller = new AbortController()
      const initialSeq = typeof runOpts.initialSeq === 'number' ? runOpts.initialSeq : 0

      // Cancel any existing stream before starting a new one.
      abortActiveStream()
      streamAbortRef.current = controller
      streamKeyRef.current = runOpts.streamKey || null

      const state = {
        serverTaskId: (runOpts.initialTaskId || '').trim() || null,
        lastSeq: initialSeq,
        done: false,
      }

      const assistant = createAssistantMessageTracker({ conversationId, assistantMessageId })
      const subAgents = createSubAgentTracker({ setSubAgentActivities, setActiveSubAgentTab })

      const handleStreamEvent = createStreamEventHandler({
        conversationId,
        assistantMessageId,
        localTaskId,
        state,
        assistant,
        subAgents,
        setIsGeneratingLocal,
        setError,
      })

      setIsGeneratingLocal(true)
      setError(null)

      openStreamConnection({
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
        isActiveController: () => streamAbortRef.current === controller,
        onComplete: () => {
          streamAbortRef.current = null
        },
      })
    },
    [abortActiveStream, setActiveSubAgentTab, setError, setIsGeneratingLocal, setSubAgentActivities]
  )

  return {
    abortActiveStream,
    runStudyMaterialsStream,
    streamKeyRef,
  }
}
