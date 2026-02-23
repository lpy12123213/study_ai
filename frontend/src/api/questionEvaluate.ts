import { apiClient } from './client'

export interface QuestionEvaluateSearchRequest {
  query: string
  subject?: string
  eduLevel?: string
  difficulty?: string
  questionType?: string
  limit?: number
  maxPages?: number
  minQualityScore?: number
}

export interface QuestionEvaluateQuestion {
  questionId: string
  stem: string
  type?: string
  difficulty?: string
  knowledgePoints?: string
  source?: string
  sourceUrl?: string
  date?: string
  qualityScore?: number
  qualityFlags?: string[]
  difficultyValue?: number
}

export interface QuestionEvaluateSearchResponse {
  success: boolean
  query: string
  subject: string
  count: number
  questions: QuestionEvaluateQuestion[]
  error?: string
}

export interface QuestionEvaluateDimensionScore {
  name: string
  score: number
  comment: string
}

export interface QuestionEvaluateResult {
  questionId: string
  verdict: string
  overallScore: number
  dimensions: QuestionEvaluateDimensionScore[]
  highlights: string[]
  issues: string[]
  summary: string
}

export interface QuestionEvaluateRequest {
  questions: QuestionEvaluateQuestion[]
  subject?: string
  requirements?: string
  model?: string
}

export interface QuestionEvaluateResponse {
  results: QuestionEvaluateResult[]
  model: string
}

function toQuestion(input: any): QuestionEvaluateQuestion | undefined {
  if (!input || typeof input !== 'object') return undefined
  const id =
    typeof (input as any).question_id === 'string'
      ? ((input as any).question_id as string)
      : typeof (input as any).questionId === 'string'
        ? ((input as any).questionId as string)
        : ''
  if (!id) return undefined

  const stem = typeof (input as any).stem === 'string' ? (input as any).stem : ''

  return {
    questionId: id,
    stem,
    type: typeof (input as any).type === 'string' ? (input as any).type : undefined,
    difficulty:
      typeof (input as any).difficulty === 'string'
        ? (input as any).difficulty
        : undefined,
    knowledgePoints:
      typeof (input as any).knowledge_points === 'string'
        ? (input as any).knowledge_points
        : typeof (input as any).knowledgePoints === 'string'
          ? (input as any).knowledgePoints
          : undefined,
    source:
      typeof (input as any).source === 'string' ? (input as any).source : undefined,
    sourceUrl:
      typeof (input as any).source_url === 'string'
        ? (input as any).source_url
        : typeof (input as any).sourceUrl === 'string'
          ? (input as any).sourceUrl
          : undefined,
    date: typeof (input as any).date === 'string' ? (input as any).date : undefined,
    qualityScore:
      typeof (input as any).quality_score === 'number'
        ? (input as any).quality_score
        : typeof (input as any).qualityScore === 'number'
          ? (input as any).qualityScore
          : undefined,
    qualityFlags: Array.isArray((input as any).quality_flags)
      ? ((input as any).quality_flags as any[]).filter((x) => typeof x === 'string')
      : Array.isArray((input as any).qualityFlags)
        ? ((input as any).qualityFlags as any[]).filter((x) => typeof x === 'string')
        : undefined,
    difficultyValue:
      typeof (input as any).difficulty_value === 'number'
        ? (input as any).difficulty_value
        : typeof (input as any).difficultyValue === 'number'
          ? (input as any).difficultyValue
          : undefined,
  }
}

function toResult(input: any): QuestionEvaluateResult | undefined {
  if (!input || typeof input !== 'object') return undefined
  const qid =
    typeof (input as any).question_id === 'string'
      ? (input as any).question_id
      : typeof (input as any).questionId === 'string'
        ? (input as any).questionId
        : ''
  if (!qid) return undefined

  const dimensions = Array.isArray((input as any).dimensions)
    ? ((input as any).dimensions as any[])
        .filter((d) => d && typeof d === 'object')
        .map((d) => ({
          name: typeof (d as any).name === 'string' ? (d as any).name : '',
          score:
            typeof (d as any).score === 'number'
              ? (d as any).score
              : Number((d as any).score) || 0,
          comment: typeof (d as any).comment === 'string' ? (d as any).comment : '',
        }))
        .filter((d) => !!d.name)
    : []

  return {
    questionId: qid,
    verdict: typeof (input as any).verdict === 'string' ? (input as any).verdict : '',
    overallScore:
      typeof (input as any).overall_score === 'number'
        ? (input as any).overall_score
        : Number((input as any).overallScore ?? (input as any).overall_score ?? 0) || 0,
    dimensions,
    highlights: Array.isArray((input as any).highlights)
      ? ((input as any).highlights as any[]).filter((x) => typeof x === 'string')
      : [],
    issues: Array.isArray((input as any).issues)
      ? ((input as any).issues as any[]).filter((x) => typeof x === 'string')
      : [],
    summary: typeof (input as any).summary === 'string' ? (input as any).summary : '',
  }
}

export async function searchQuestions(
  req: QuestionEvaluateSearchRequest,
): Promise<QuestionEvaluateSearchResponse> {
  const response = await apiClient.post<unknown>('/question-evaluate/search', {
    query: req.query,
    subject: req.subject,
    edu_level: req.eduLevel,
    difficulty: req.difficulty,
    question_type: req.questionType,
    limit: req.limit,
    max_pages: req.maxPages,
    min_quality_score: req.minQualityScore,
  })

  const data = response.data as any
  const rawQuestions: unknown[] = Array.isArray(data?.questions) ? data.questions : []
  const questions = rawQuestions.map(toQuestion).filter((q): q is QuestionEvaluateQuestion => !!q)

  return {
    success: Boolean(data?.success),
    query: typeof data?.query === 'string' ? data.query : req.query,
    subject: typeof data?.subject === 'string' ? data.subject : req.subject || '',
    count: typeof data?.count === 'number' ? data.count : questions.length,
    questions,
    error: typeof data?.error === 'string' ? data.error : undefined,
  }
}

export async function evaluateQuestions(
  req: QuestionEvaluateRequest,
): Promise<QuestionEvaluateResponse> {
  const response = await apiClient.post<unknown>('/question-evaluate/evaluate', {
    subject: req.subject,
    requirements: req.requirements,
    model: req.model,
    questions: (req.questions || []).map((q) => ({
      question_id: q.questionId,
      stem: q.stem,
      type: q.type,
      difficulty: q.difficulty,
      knowledge_points: q.knowledgePoints,
      source: q.source,
      source_url: q.sourceUrl,
      date: q.date,
      quality_score: q.qualityScore,
      quality_flags: q.qualityFlags,
      difficulty_value: q.difficultyValue,
    })),
  })

  const data = response.data as any
  const rawResults: unknown[] = Array.isArray(data?.results) ? data.results : []
  const results = rawResults.map(toResult).filter((r): r is QuestionEvaluateResult => !!r)

  return {
    results,
    model: typeof data?.model === 'string' ? data.model : '',
  }
}
