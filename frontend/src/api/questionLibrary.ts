import { apiClient, fetchSSE, fetchSSERequest } from '@/api/client'
import { streamTask } from '@/api/tasks'
import { normalizeSseEnvelope, type SseEnvelope } from '@/lib/sse'

export type QuestionOrigin = 'crawled' | 'ai' | string

export interface QuestionLibraryListItem {
  question_id: string
  subject: string
  origin: QuestionOrigin
  hidden: boolean
  starred?: boolean
  has_answer?: boolean
  has_analysis?: boolean
  ai_score?: number | null
  ai_verdict?: string
  ai_dimensions_json?: string
  ai_summary?: string
  updated_at?: string
  stem?: string
  question_type?: string
  difficulty?: string
  difficulty_value?: number | null
  knowledge_point?: string
  knowledge_points_json?: string
  source_url?: string
  quality_score?: number | null
  source?: string
  date?: string
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
  difficulty_value_min?: number
  difficulty_value_max?: number
  require_difficulty_value?: boolean
  task_id?: string
}

export interface GenerateQuestionsPayload {
  subject: string
  topic: string
  difficulty?: string
  question_type?: string
  count?: number
  use_study_archive?: boolean
  use_reference_questions?: boolean
  reference_source?: 'any' | 'gaokao' | 'mock' | 'joint'
  reference_year_range?: 'all' | '3' | '5'
  session_id?: string
  mode?: 'standard' | 'infinite'
  grade_id?: string
  textbook_version_id?: string
  knowledge_point_ids?: string[]
  knowledge_points?: string[]
  append?: boolean
  stream_reasoning?: boolean
  task_id?: string
}

export interface QuestionLibraryDraftQuestion {
  question_id: string
  stem: string
  answer: string
  analysis: string
  keep?: boolean
  diagrams?: Array<{
    kind?: string
    url: string
    filename?: string
    media_id?: string
    alt?: string
    caption?: string
    markdown?: string
  }>
  review_status?: 'pending_review' | 'in_review' | 'approved' | 'rejected' | 'confirmed' | 'committed'
  review?: {
    verdict: string
    overall_score: number
    dimensions: Array<{ name: string; score: number; comment: string }>
    highlights: string[]
    issues: string[]
    summary: string
    model: string
  } | null
}

export interface QuestionLibraryPreviewResponse {
  success: boolean
  preview_id: string
  session_id?: string
  task_id?: string
  subject: string
  topic: string
  mode?: 'standard' | 'infinite'
  use_reference_questions?: boolean
  reference_source?: 'any' | 'gaokao' | 'mock' | 'joint'
  reference_year_range?: 'all' | '3' | '5'
  count: number
  draft_questions: QuestionLibraryDraftQuestion[]
}

export interface QuestionLibraryLatestPendingPreviewResponse {
  success: boolean
  preview: Omit<QuestionLibraryPreviewResponse, 'success'> | null
}

export interface QuestionLibraryCommitPreviewResponse {
  success: boolean
  preview_id: string
  inserted: number
  subject: string
  count: number
  question_ids: string[]
}

export interface RegenerateQuestionLibrarySectionPayload {
  question_id: string
  section_key: 'stem' | 'answer' | 'analysis'
}

export interface RegenerateQuestionLibrarySectionEvent {
  preview_id?: string
  question_id?: string
  section_key?: 'stem' | 'answer' | 'analysis'
  content?: string
  stage?: string
  progress?: number
  draft_question?: QuestionLibraryDraftQuestion
  message?: string
}

export interface QuestionLibraryReasoningBlock {
  id: string
  task_id?: string
  stage_id?: string
  stage_label?: string
  source?: 'raw' | 'trace' | string
  content: string
  created_at?: string
}

export interface QuestionLibrarySessionSummary {
  session_id: string
  preview_id?: string
  status: string
  mode: 'standard' | 'infinite' | string
  subject: string
  topic: string
  count: number
  use_reference_questions?: boolean
  reference_source?: 'any' | 'gaokao' | 'mock' | 'joint'
  reference_year_range?: 'all' | '3' | '5'
  task_ids: string[]
  latest_task_id?: string
  updated_at_s?: number
  created_at_s?: number
  reasoning_blocks_count?: number
  confirmed_question_ids?: string[]
  stop_requested?: boolean
}

export interface QuestionLibrarySessionDetail extends QuestionLibrarySessionSummary {
  difficulty?: string
  question_type?: string
  use_study_archive?: boolean
  grade_id?: string
  textbook_version_id?: string
  knowledge_point_ids?: string[]
  knowledge_points?: string[]
  stream_reasoning?: boolean
  draft_questions: QuestionLibraryDraftQuestion[]
  reasoning_blocks: QuestionLibraryReasoningBlock[]
  task_events: SseEnvelope[]
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

export async function starQuestion(questionId: string): Promise<void> {
  const qid = String(questionId || '').trim()
  if (!qid) throw new Error('missing_question_id')
  await apiClient.post(`/question-library/items/${encodeURIComponent(qid)}/star`)
}

export async function unstarQuestion(questionId: string): Promise<void> {
  const qid = String(questionId || '').trim()
  if (!qid) throw new Error('missing_question_id')
  await apiClient.post(`/question-library/items/${encodeURIComponent(qid)}/unstar`)
}

export async function exportQuestionToBasket(questionId: string): Promise<any> {
  const qid = String(questionId || '').trim()
  if (!qid) throw new Error('missing_question_id')
  const resp = await apiClient.post(`/question-library/items/${encodeURIComponent(qid)}/export-to-basket`)
  return resp.data as any
}

export async function bulkDeleteQuestionLibraryItems(questionIds: string[]): Promise<{ success: boolean; deleted: number }> {
  const ids = Array.from(
    new Set((questionIds || []).map((x) => String(x || '').trim()).filter(Boolean))
  )
  if (ids.length === 0) throw new Error('question_ids_required')
  const resp = await apiClient.post('/question-library/items/bulk-delete', { question_ids: ids })
  return resp.data as any
}

export async function getQuestionLibraryPreview(previewId: string): Promise<QuestionLibraryPreviewResponse> {
  const pid = String(previewId || '').trim()
  if (!pid) throw new Error('missing_preview_id')
  const resp = await apiClient.get(`/question-library/previews/${encodeURIComponent(pid)}`)
  return resp.data as QuestionLibraryPreviewResponse
}

export async function getLatestPendingQuestionLibraryPreview(): Promise<QuestionLibraryLatestPendingPreviewResponse> {
  const resp = await apiClient.get('/question-library/previews/latest/pending')
  return resp.data as QuestionLibraryLatestPendingPreviewResponse
}

export async function listQuestionLibrarySessions(): Promise<{ success: boolean; sessions: QuestionLibrarySessionSummary[] }> {
  const resp = await apiClient.get('/question-library/sessions')
  return resp.data as { success: boolean; sessions: QuestionLibrarySessionSummary[] }
}

export async function getQuestionLibrarySession(sessionId: string): Promise<{ success: boolean; session: QuestionLibrarySessionDetail }> {
  const sid = String(sessionId || '').trim()
  if (!sid) throw new Error('missing_session_id')
  const resp = await apiClient.get(`/question-library/sessions/${encodeURIComponent(sid)}`)
  return resp.data as { success: boolean; session: QuestionLibrarySessionDetail }
}

export async function stopQuestionLibrarySession(sessionId: string): Promise<{ success: boolean; session_id: string; status: string }> {
  const sid = String(sessionId || '').trim()
  if (!sid) throw new Error('missing_session_id')
  const resp = await apiClient.post(`/question-library/sessions/${encodeURIComponent(sid)}/stop`)
  return resp.data as { success: boolean; session_id: string; status: string }
}

export async function archiveQuestionLibrarySession(sessionId: string): Promise<{ success: boolean; session_id: string; status: string }> {
  const sid = String(sessionId || '').trim()
  if (!sid) throw new Error('missing_session_id')
  const resp = await apiClient.post(`/question-library/sessions/${encodeURIComponent(sid)}/archive`)
  return resp.data as { success: boolean; session_id: string; status: string }
}

export async function reviewQuestionLibrarySessionQuestion(
  sessionId: string,
  questionId: string
): Promise<{ success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }> {
  const sid = String(sessionId || '').trim()
  const qid = String(questionId || '').trim()
  if (!sid) throw new Error('missing_session_id')
  if (!qid) throw new Error('missing_question_id')
  const resp = await apiClient.post(`/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/review`, undefined, { timeout: 120_000 })
  return resp.data as { success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }
}

export async function approveQuestionLibrarySessionQuestion(
  sessionId: string,
  questionId: string
): Promise<{ success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }> {
  const sid = String(sessionId || '').trim()
  const qid = String(questionId || '').trim()
  if (!sid) throw new Error('missing_session_id')
  if (!qid) throw new Error('missing_question_id')
  const resp = await apiClient.post(`/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/approve`)
  return resp.data as { success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }
}

export async function rejectQuestionLibrarySessionQuestion(
  sessionId: string,
  questionId: string
): Promise<{ success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }> {
  const sid = String(sessionId || '').trim()
  const qid = String(questionId || '').trim()
  if (!sid) throw new Error('missing_session_id')
  if (!qid) throw new Error('missing_question_id')
  const resp = await apiClient.post(`/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/reject`)
  return resp.data as { success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }
}

export async function confirmQuestionLibrarySessionQuestion(
  sessionId: string,
  questionId: string
): Promise<{ success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }> {
  const sid = String(sessionId || '').trim()
  const qid = String(questionId || '').trim()
  if (!sid) throw new Error('missing_session_id')
  if (!qid) throw new Error('missing_question_id')
  const resp = await apiClient.post(`/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/confirm`)
  return resp.data as { success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }
}

export async function unconfirmQuestionLibrarySessionQuestion(
  sessionId: string,
  questionId: string
): Promise<{ success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }> {
  const sid = String(sessionId || '').trim()
  const qid = String(questionId || '').trim()
  if (!sid) throw new Error('missing_session_id')
  if (!qid) throw new Error('missing_question_id')
  const resp = await apiClient.post(`/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/unconfirm`)
  return resp.data as { success: boolean; session_id: string; question: QuestionLibraryDraftQuestion }
}

export async function commitQuestionLibraryPreview(
  previewId: string,
  questions: QuestionLibraryDraftQuestion[]
): Promise<QuestionLibraryCommitPreviewResponse> {
  const pid = String(previewId || '').trim()
  if (!pid) throw new Error('missing_preview_id')
  const resp = await apiClient.post(`/question-library/previews/${encodeURIComponent(pid)}/commit`, { questions })
  return resp.data as QuestionLibraryCommitPreviewResponse
}

export async function discardQuestionLibraryPreview(previewId: string): Promise<{ success: boolean }> {
  const pid = String(previewId || '').trim()
  if (!pid) throw new Error('missing_preview_id')
  const resp = await apiClient.post(`/question-library/previews/${encodeURIComponent(pid)}/discard`)
  return resp.data as any
}

export function regenerateQuestionLibrarySection(
  previewId: string,
  payload: RegenerateQuestionLibrarySectionPayload,
  onEvent: (event: SseEnvelope<RegenerateQuestionLibrarySectionEvent>) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: {
    signal?: AbortSignal
  }
): void {
  const pid = String(previewId || '').trim()
  if (!pid) throw new Error('missing_preview_id')
  fetchSSE(
    `/question-library/previews/${encodeURIComponent(pid)}/regenerate-section`,
    payload,
    (data) => onEvent(normalizeQuestionLibraryTaskEvent(data) as SseEnvelope<RegenerateQuestionLibrarySectionEvent>),
    onError,
    onComplete,
    { signal: options?.signal }
  )
}

export function crawlQuestions(
  payload: CrawlQuestionsPayload,
  onEvent: (event: SseEnvelope) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): void {
  apiClient
    .post('/tasks/question-library/crawl', payload)
    .then((res) => {
      const taskId = String((res.data as any)?.taskId || (payload as any)?.task_id || '').trim()
      if (!taskId) throw new Error('missing_task_id')
      streamTask(
        taskId,
        0,
        (evt) => onEvent(normalizeQuestionLibraryTaskEvent(evt)),
        onError,
        onComplete
      )
    })
    .catch((err: any) => {
      const message = typeof err?.message === 'string' ? err.message : 'request_failed'
      onError?.(err instanceof Error ? err : new Error(message))
    })
}

export function generateQuestions(
  payload: GenerateQuestionsPayload,
  onEvent: (event: SseEnvelope) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): void {
  apiClient
    .post('/tasks/question-library/generate', payload)
    .then((res) => {
      const taskId = String((res.data as any)?.taskId || (payload as any)?.task_id || '').trim()
      if (!taskId) throw new Error('missing_task_id')
      streamTask(
        taskId,
        0,
        (evt) => onEvent(normalizeQuestionLibraryTaskEvent(evt)),
        onError,
        onComplete
      )
    })
    .catch((err: any) => {
      const message = typeof err?.message === 'string' ? err.message : 'request_failed'
      onError?.(err instanceof Error ? err : new Error(message))
    })
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

export const questionLibraryApi = {
  listQuestionLibrary,
  getQuestionLibraryItem,
  hideQuestion,
  unhideQuestion,
  starQuestion,
  unstarQuestion,
  exportQuestionToBasket,
  bulkDeleteQuestionLibraryItems,
  list: async (params?: { search?: string }): Promise<{ data: any }> => {
    const response = await listQuestionLibrary({
      q: String(params?.search || '').trim() || undefined,
      limit: 100,
      offset: 0,
    })
    return {
      data: {
        questions: response.items.map((item) => ({
          id: item.question_id,
          content: item.stem || item.question_id,
          type: item.question_type || item.origin || '',
        })),
      },
    }
  },
}
