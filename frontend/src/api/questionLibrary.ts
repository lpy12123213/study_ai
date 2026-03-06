import { apiClient, fetchSSE, fetchSSERequest } from '@/api/client'
import { normalizeSseEnvelope, type SseEnvelope } from '@/lib/sse'

export type QuestionOrigin = 'crawled' | 'ai' | string

export interface QuestionLibraryListItem {
  question_id: string
  subject: string
  origin: QuestionOrigin
  hidden: boolean
  ai_score?: number | null
  ai_verdict?: string
  ai_dimensions_json?: string
  ai_summary?: string
  updated_at?: string
  stem?: string
}

export interface QuestionLibraryListResponse {
  total: number
  limit: number
  offset: number
  items: QuestionLibraryListItem[]
}

export interface QuestionLibraryListParams {
  subject?: string
  origin?: QuestionOrigin
  hidden?: '0' | '1' | 'all'
  q?: string
  min_score?: number
  sort?: 'updated_at' | 'ai_score' | string
  order?: 'desc' | 'asc' | string
  limit?: number
  offset?: number
}

export interface QuestionCacheRecord {
  question_id: string
  subject?: string
  question_type?: string
  difficulty?: string
  knowledge_point?: string
  source_url?: string
  stem?: string
  answer?: string
  analysis?: string
  updated_at?: string
}

export interface QuestionLibraryDetailResponse {
  library_item: QuestionLibraryListItem | null
  question_cache: QuestionCacheRecord | null
}

export interface CrawlQuestionsPayload {
  subject: string
  edu_level?: string
  query: string
  difficulty?: string
  question_type?: string
  limit?: number
  max_pages?: number
  min_quality_score?: number
  task_id?: string
}

export interface GenerateQuestionsPayload {
  subject: string
  topic: string
  difficulty?: string
  question_type?: string
  count?: number
  use_study_archive?: boolean
  task_id?: string
}

export interface ScoreQuestionLibraryBatchPayload {
  subject: string
  limit?: number
  only_unscored?: boolean
  task_id?: string
}

export function normalizeQuestionLibraryTaskEvent(input: unknown): SseEnvelope {
  return normalizeSseEnvelope(input)
}

export async function listQuestionLibrary(params: QuestionLibraryListParams): Promise<QuestionLibraryListResponse> {
  const resp = await apiClient.get('/question-library/items', { params })
  return resp.data as QuestionLibraryListResponse
}

export async function getQuestionLibraryItem(questionId: string): Promise<QuestionLibraryDetailResponse> {
  const qid = String(questionId || '').trim()
  if (!qid) throw new Error('missing_question_id')
  const resp = await apiClient.get(`/question-library/items/${encodeURIComponent(qid)}`)
  return resp.data as QuestionLibraryDetailResponse
}

export async function hideQuestion(questionId: string): Promise<void> {
  const qid = String(questionId || '').trim()
  if (!qid) throw new Error('missing_question_id')
  await apiClient.post(`/question-library/items/${encodeURIComponent(qid)}/hide`)
}

export async function unhideQuestion(questionId: string): Promise<void> {
  const qid = String(questionId || '').trim()
  if (!qid) throw new Error('missing_question_id')
  await apiClient.post(`/question-library/items/${encodeURIComponent(qid)}/unhide`)
}

export function crawlQuestions(
  payload: CrawlQuestionsPayload,
  onEvent: (event: SseEnvelope) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): void {
  fetchSSE(
    '/question-library/crawl',
    payload,
    (data) => onEvent(normalizeQuestionLibraryTaskEvent(data)),
    onError,
    onComplete
  )
}

export function generateQuestions(
  payload: GenerateQuestionsPayload,
  onEvent: (event: SseEnvelope) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): void {
  fetchSSE(
    '/question-library/generate',
    payload,
    (data) => onEvent(normalizeQuestionLibraryTaskEvent(data)),
    onError,
    onComplete
  )
}

export async function scoreQuestionLibraryBatch(payload: ScoreQuestionLibraryBatchPayload): Promise<any> {
  const resp = await apiClient.post('/question-library/score', payload)
  return resp.data
}

export function streamQuestionLibraryTask(
  taskId: string,
  afterSeq: number,
  onEvent: (event: SseEnvelope) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): void {
  const id = String(taskId || '').trim()
  if (!id) throw new Error('missing_task_id')
  fetchSSERequest(
    `/question-library/tasks/${encodeURIComponent(id)}/stream?after_seq=${Math.max(0, afterSeq || 0)}`,
    { method: 'GET' },
    (data) => onEvent(normalizeQuestionLibraryTaskEvent(data)),
    onError,
    onComplete
  )
}
