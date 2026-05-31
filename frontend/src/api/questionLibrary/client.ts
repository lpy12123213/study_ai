import { apiClient } from '@/api/client'
import type {
  ExportQuestionToBasketResponse,
  QuestionLibraryCommitPreviewResponse,
  QuestionLibraryCompatListResponse,
  QuestionLibraryDetailResponse,
  QuestionLibraryDraftQuestion,
  QuestionLibraryLatestPendingPreviewResponse,
  QuestionLibraryListParams,
  QuestionLibraryListResponse,
  QuestionLibraryPreviewResponse,
  QuestionLibrarySessionDetail,
  QuestionLibrarySessionSummary,
  ScoreQuestionLibraryBatchPayload,
  ScoreQuestionLibraryBatchResponse,
} from './types'

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

export async function exportQuestionToBasket(questionId: string): Promise<ExportQuestionToBasketResponse> {
  const qid = String(questionId || '').trim()
  if (!qid) throw new Error('missing_question_id')
  const resp = await apiClient.post<ExportQuestionToBasketResponse>(`/question-library/items/${encodeURIComponent(qid)}/export-to-basket`)
  return resp.data
}

export async function bulkDeleteQuestionLibraryItems(questionIds: string[]): Promise<{ success: boolean; deleted: number }> {
  const ids = Array.from(
    new Set((questionIds || []).map((x) => String(x || '').trim()).filter(Boolean))
  )
  if (ids.length === 0) throw new Error('question_ids_required')
  const resp = await apiClient.post<{ success: boolean; deleted: number }>('/question-library/items/bulk-delete', { question_ids: ids })
  return resp.data
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
  const resp = await apiClient.post<{ success: boolean }>(`/question-library/previews/${encodeURIComponent(pid)}/discard`)
  return resp.data
}

export async function scoreQuestionLibraryBatch(payload: ScoreQuestionLibraryBatchPayload): Promise<ScoreQuestionLibraryBatchResponse> {
  const resp = await apiClient.post<ScoreQuestionLibraryBatchResponse>('/question-library/score', payload)
  return resp.data
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
  list: async (params?: { search?: string }): Promise<{ data: QuestionLibraryCompatListResponse }> => {
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
