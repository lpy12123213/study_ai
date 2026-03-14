export type AiGenerateSectionStatus = 'idle' | 'streaming' | 'done' | 'failed'

export interface AiGenerateSectionState {
  label: string
  content: string
  status: AiGenerateSectionStatus
  updatedAt: string | null
  locked: boolean
  edited: boolean
}

export interface AiGenerateDraftCard {
  id: string
  questionId: string
  title: string
  index: number
  keep: boolean
  status: 'queued' | 'streaming' | 'ready' | 'failed'
  sections: {
    stem: AiGenerateSectionState
    answer: AiGenerateSectionState
    analysis: AiGenerateSectionState
  }
}

export interface AiGenerateMissionSummary {
  subject: string
  topic: string
  count: number
}

export interface AiGenerateStudioSession {
  previewId: string
  taskId: string
  mission: AiGenerateMissionSummary
  drafts: AiGenerateDraftCard[]
  confirmedIds: string[]
}
