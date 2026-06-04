export type ExamMode = 'timed' | 'untimed'
export type ExamSessionStatus = 'in_progress' | 'submitted' | 'expired'

export interface ExamQuestion {
  questionId: string
  order: number
  type: string
  questionType: string
  stem: string
  difficulty?: string
  knowledgePoint?: string
  maxScore: number
  sourceUrl?: string
  studentAnswer?: StudentAnswer
}

export interface StudentAnswer {
  questionId: string
  questionType?: string
  questionOrder?: number
  selectedOptions: string[]
  fillBlankText: string
  handwritingImagePath?: string
  handwritingImageUrl?: string
  textAnswer: string
  isCorrect?: boolean | null
  score?: number
  maxScore?: number
  gradingJson?: Record<string, unknown>
  autoSavedAt?: string
}

export interface ExamSession {
  sessionId: string
  paperId: number
  paperName: string
  mode: ExamMode
  timeLimitMinutes?: number | null
  startedAt?: string | null
  submittedAt?: string | null
  expiresAt?: string | null
  status: ExamSessionStatus
  totalScore: number
  maxScore: number
  questions: ExamQuestion[]
  answers?: StudentAnswer[]
}

export interface ExamResult {
  sessionId: string
  totalScore: number
  maxScore: number
  scoreRatio: number
  objectiveCorrect: number
  objectiveTotal: number
  subjectiveScore: number
  subjectiveMax: number
  breakdown: Array<Record<string, unknown>>
  aiFeedback: Record<string, unknown>
  createdAt?: string | null
}

export interface StartExamRequest {
  paperId: number
  mode: ExamMode
  timeLimitMinutes?: number | null
}

export interface SaveExamAnswerRequest {
  questionId: string
  questionType?: string
  selectedOptions?: string[]
  fillBlankText?: string
  handwritingImagePath?: string
  textAnswer?: string
}
