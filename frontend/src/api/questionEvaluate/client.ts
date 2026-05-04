import { apiClient } from '../client'
import { getTask } from '../tasks'

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
  taskId?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object')
}

function recordString(value: unknown, key: string): string | undefined {
  if (!isRecord(value)) return undefined
  const item = value[key]
  return typeof item === 'string' ? item : undefined
}

function recordNumber(value: unknown, key: string): number | undefined {
  if (!isRecord(value)) return undefined
  const item = value[key]
  return typeof item === 'number' ? item : undefined
}

function recordStringArray(value: unknown, key: string): string[] | undefined {
  if (!isRecord(value)) return undefined
  const item = value[key]
  return Array.isArray(item) ? item.filter((entry): entry is string => typeof entry === 'string') : undefined
}

function toQuestion(input: unknown): QuestionEvaluateQuestion | undefined {
  if (!isRecord(input)) return undefined
  const id =
    recordString(input, 'question_id') || recordString(input, 'questionId') || ''
  if (!id) return undefined

  const stem = recordString(input, 'stem') || ''

  return {
    questionId: id,
    stem,
    type: recordString(input, 'type'),
    difficulty: recordString(input, 'difficulty'),
    knowledgePoints: recordString(input, 'knowledge_points') || recordString(input, 'knowledgePoints'),
    source: recordString(input, 'source'),
    sourceUrl: recordString(input, 'source_url') || recordString(input, 'sourceUrl'),
    date: recordString(input, 'date'),
    qualityScore: recordNumber(input, 'quality_score') ?? recordNumber(input, 'qualityScore'),
    qualityFlags: recordStringArray(input, 'quality_flags') || recordStringArray(input, 'qualityFlags'),
    difficultyValue: recordNumber(input, 'difficulty_value') ?? recordNumber(input, 'difficultyValue'),
  }
}

function toResult(input: unknown): QuestionEvaluateResult | undefined {
  if (!isRecord(input)) return undefined
  const qid =
    recordString(input, 'question_id') || recordString(input, 'questionId') || ''
  if (!qid) return undefined

  const dimensions = Array.isArray(input.dimensions)
    ? input.dimensions
        .filter((d): d is Record<string, unknown> => isRecord(d))
        .map((d) => ({
          name: recordString(d, 'name') || '',
          score:
            recordNumber(d, 'score') ?? (Number(d.score) || 0),
          comment: recordString(d, 'comment') || '',
        }))
        .filter((d) => !!d.name)
    : []

  return {
    questionId: qid,
    verdict: recordString(input, 'verdict') || '',
    overallScore:
      recordNumber(input, 'overall_score') ?? (Number(input.overallScore ?? input.overall_score ?? 0) || 0),
    dimensions,
    highlights: recordStringArray(input, 'highlights') || [],
    issues: recordStringArray(input, 'issues') || [],
    summary: recordString(input, 'summary') || '',
  }
}

function toEvaluateResponse(input: unknown, taskId?: string): QuestionEvaluateResponse {
  const source = isRecord(input) ? input : {}
  const rawResults: unknown[] = Array.isArray(source.results) ? source.results : []
  const results = rawResults.map(toResult).filter((r): r is QuestionEvaluateResult => !!r)

  return {
    results,
    model: recordString(source, 'model') || '',
    taskId,
  }
}

function findDonePayload(events: unknown): unknown {
  if (!Array.isArray(events)) return undefined
  const items = events as unknown[]
  for (let i = items.length - 1; i >= 0; i -= 1) {
    const event = items[i]
    if (isRecord(event) && event.type === 'done' && isRecord(event.data)) return event.data
  }
  return undefined
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms))
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

  const data = isRecord(response.data) ? response.data : {}
  const rawQuestions: unknown[] = Array.isArray(data.questions) ? data.questions : []
  const questions = rawQuestions.map(toQuestion).filter((q): q is QuestionEvaluateQuestion => !!q)

  return {
    success: Boolean(data.success),
    query: recordString(data, 'query') || req.query,
    subject: recordString(data, 'subject') || req.subject || '',
    count: recordNumber(data, 'count') ?? questions.length,
    questions,
    error: recordString(data, 'error'),
  }
}

export async function evaluateQuestions(
  req: QuestionEvaluateRequest,
): Promise<QuestionEvaluateResponse> {
  const response = await apiClient.post<unknown>('/tasks/question-evaluate/evaluate', {
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

  const taskId = String(recordString(response.data, 'taskId') || '')
  if (!taskId) throw new Error('missing_task_id')

  for (;;) {
    const task = await getTask(taskId, { includeEvents: true, eventsLimit: 200 })
    const status = String(task.status || '')

    if (status === 'completed') {
      const payload = isRecord(task.result)
        ? task.result
        : findDonePayload(task.events)
      return toEvaluateResponse(payload || {}, taskId)
    }

    if (status === 'failed' || status === 'canceled') {
      const error = task.error
      const taskErrorMessage = recordString(error, 'message')
      const message =
        typeof error === 'string'
          ? error
          : taskErrorMessage
            ? taskErrorMessage
            : '鉴别失败'
      throw new Error(message)
    }

    await sleep(800)
  }
}
