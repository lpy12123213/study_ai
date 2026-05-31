import type { Dispatch, SetStateAction } from 'react'
import type { SubAgentActivity } from '@/features/generation/studyMaterials/types'

export type StudyMaterialsStreamRequest = { url: string; method: 'GET' | 'POST'; body?: unknown }

export type RunStudyMaterialsStreamOptions = {
  conversationId: string
  assistantMessageId: string
  request: StudyMaterialsStreamRequest
  localTaskId?: string
  initialTaskId?: string
  initialSeq?: number
  streamKey?: string
}

export type StreamRecord = Record<string, unknown>

/** State setters/callbacks shared across the stream session helpers. */
export type StudyMaterialsStreamCallbacks = {
  setIsGeneratingLocal: (next: boolean) => void
  setError: (next: unknown) => void
  setSubAgentActivities: Dispatch<SetStateAction<SubAgentActivity[]>>
  setActiveSubAgentTab: Dispatch<SetStateAction<string | null>>
}
