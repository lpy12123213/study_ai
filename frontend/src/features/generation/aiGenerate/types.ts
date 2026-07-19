import type {
  IntuitionFeedbackMode,
  IntuitionKind,
  IntuitionPacket,
  IntuitionPracticeConfig,
  IntuitionPracticeGoal,
  IntuitionPracticeAttempt,
} from '@/api/questionLibrary'

export type AiGenerateSectionStatus = 'idle' | 'streaming' | 'done' | 'failed'
export type AiGenerateReviewStatus = 'pending_review' | 'in_review' | 'approved' | 'rejected' | 'confirmed' | 'committed'
export type AiGenerateSessionMode = 'standard' | 'infinite'

export const DEFAULT_INTUITION_PRACTICE: IntuitionPracticeConfig = {
  practice_goal: 'structural_intuition',
  intuition_kinds: ['prediction', 'representation', 'invariant'],
  packet_size: 3,
  feedback_mode: 'guided',
}

const PRACTICE_GOALS = new Set<IntuitionPracticeGoal>([
  'fluency',
  'structural_intuition',
  'intuition_correction',
  'transfer',
  'solution_appreciation',
])
const INTUITION_KINDS = new Set<IntuitionKind>([
  'prediction',
  'representation',
  'invariant',
  'boundary',
  'counterexample',
  'solution_comparison',
])
const FEEDBACK_MODES = new Set<IntuitionFeedbackMode>(['guided', 'concise', 'reflective'])

export function normalizeIntuitionPractice(input: unknown): IntuitionPracticeConfig {
  const raw = input && typeof input === 'object' ? (input as Record<string, unknown>) : {}
  const goal = String(raw.practice_goal || '').trim() as IntuitionPracticeGoal
  const feedbackMode = String(raw.feedback_mode || '').trim() as IntuitionFeedbackMode
  const kinds = Array.isArray(raw.intuition_kinds)
    ? raw.intuition_kinds
        .map((item) => String(item || '').trim() as IntuitionKind)
        .filter((item, index, values) => INTUITION_KINDS.has(item) && values.indexOf(item) === index)
    : []
  const rawPacketSize = Number(raw.packet_size)
  const normalizedGoal = PRACTICE_GOALS.has(goal) ? goal : DEFAULT_INTUITION_PRACTICE.practice_goal
  const minimumPacketSize = normalizedGoal === 'solution_appreciation' ? 4 : 3

  return {
    practice_goal: normalizedGoal,
    intuition_kinds: kinds.length > 0 ? kinds : [...DEFAULT_INTUITION_PRACTICE.intuition_kinds],
    packet_size: Number.isFinite(rawPacketSize)
      ? Math.max(minimumPacketSize, Math.min(5, Math.round(rawPacketSize)))
      : minimumPacketSize,
    feedback_mode: FEEDBACK_MODES.has(feedbackMode) ? feedbackMode : DEFAULT_INTUITION_PRACTICE.feedback_mode,
  }
}

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
  intuitionPacket?: IntuitionPacket
  practiceState?: IntuitionPracticeAttempt
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
  intuitionPractice?: IntuitionPracticeConfig
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
