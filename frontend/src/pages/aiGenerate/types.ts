export type AiGenerateSectionStatus = 'idle' | 'streaming' | 'done' | 'failed'
export type AiGenerateReviewStatus = 'pending_review' | 'in_review' | 'approved' | 'rejected' | 'confirmed' | 'committed'
export type AiGenerateSessionMode = 'standard' | 'infinite'

export interface AiGenerateSectionState {
  label: string
  content: string
  status: AiGenerateSectionStatus
  updatedAt: string | null
  locked: boolean
  edited: boolean
}

export interface AiGenerateReviewSummary {
  verdict: string
  overallScore: number
  dimensions: Array<{ name: string; score: number; comment: string }>
  highlights: string[]
  issues: string[]
  summary: string
  model: string
}

export interface AiGenerateDiagram {
  kind?: string
  url: string
  filename?: string
  mediaId?: string
  alt?: string
  caption?: string
  markdown?: string
}

export interface AiGenerateDraftCard {
  id: string
  questionId: string
  title: string
  index: number
  keep: boolean
  status: 'queued' | 'streaming' | 'ready' | 'failed'
  reviewStatus: AiGenerateReviewStatus
  review: AiGenerateReviewSummary | null
  diagrams?: AiGenerateDiagram[]
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
  difficulty?: string
  questionType?: string
  useStudyArchive?: boolean
  useReferenceQuestions?: boolean
  referenceSource?: 'any' | 'gaokao' | 'mock' | 'joint' | string
  referenceYearRange?: 'all' | '3' | '5' | string
  gradeId?: string
  textbookVersionId?: string
  knowledgePointIds?: string[]
  knowledgePoints?: string[]
}

export interface AiGenerateReasonBlock {
  id: string
  taskId?: string
  stageId?: string
  stageLabel?: string
  source?: 'raw' | 'trace' | string
  content: string
  createdAt?: string
}

export interface AiGenerateKnowledgeNode {
  id: string
  label: string
  type: 'root' | 'chapter' | 'knowledge_point' | string
  selectable?: boolean
  children?: AiGenerateKnowledgeNode[]
}

export interface AiGenerateSessionSummary {
  sessionId: string
  previewId: string
  status: string
  mode: AiGenerateSessionMode
  subject: string
  topic: string
  count: number
  latestTaskId: string
  taskIds: string[]
  reasoningBlocksCount: number
  confirmedIds: string[]
  stopRequested: boolean
}

export interface AiGenerateStudioSession {
  sessionId: string
  previewId: string
  taskId: string
  status: string
  mode: AiGenerateSessionMode
  stopRequested: boolean
  mission: AiGenerateMissionSummary
  drafts: AiGenerateDraftCard[]
  confirmedIds: string[]
  reasoningBlocks: AiGenerateReasonBlock[]
  taskEvents: Array<{ taskId?: string; seq?: number; type?: string; data?: any; created_at?: string }>
}
