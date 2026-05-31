import { apiClient } from '../client'

/**
 * Essay-evaluation API client.
 *
 * Mirrors the FastAPI surface in ``backend/api/essay_evaluation.py``:
 *
 * - ``POST /essay-evaluations/evaluate`` synchronous one-shot scoring.
 * - ``GET /essay-evaluations`` paginated history list (no ``essay_text``).
 * - ``GET /essay-evaluations/:id`` full record with ``essay_text``.
 * - ``DELETE /essay-evaluations/:id`` removes a record.
 *
 * For long-running scoring with SSE progress, submit through the canonical
 * task endpoint (``POST /api/tasks/essay-evaluations/evaluate``) and connect
 * to the resulting ``taskId`` via the existing tasks SSE helper.
 */

export type EssayLanguage = 'zh' | 'en'

export type EssayType = 'argumentative' | 'narrative' | 'expository' | 'applied' | 'other'

export type GradeBand = 'primary' | 'junior' | 'senior' | 'ielts' | 'toefl' | 'other'

export interface EssayEvaluationRequest {
  text: string
  language?: EssayLanguage
  essay_type?: EssayType
  grade_band?: GradeBand
  subject?: string
  topic?: string
  rubric_max_score?: number
  requirements?: string
}

export interface EssayDimensionScore {
  name: string
  score: number
  max_score: number
  weight: number
  comment: string
}

export interface EssayParagraphFeedback {
  index: number
  excerpt: string
  issues: string[]
  suggestion: string
}

export interface EssayEvaluationResult {
  score_total: number
  score_max: number
  grade: string
  summary: string
  strengths: string[]
  weaknesses: string[]
  suggestions: string[]
  scores: EssayDimensionScore[]
  paragraph_feedback: EssayParagraphFeedback[]
  rewrite: string
  model: string
  language: EssayLanguage
  essay_type: EssayType
  grade_band: GradeBand
}

export interface EssayEvaluationRecordSummary {
  id: number
  user_id: string
  subject: string
  topic: string
  essay_type: string
  grade_band: string
  language: EssayLanguage
  score_total: number
  score_max: number
  grade: string
  scores: EssayDimensionScore[]
  summary: string
  strengths: string[]
  weaknesses: string[]
  suggestions: string[]
  paragraph_feedback: EssayParagraphFeedback[]
  rewrite: string
  model: string
  created_at: string
  updated_at: string
}

export interface EssayEvaluationRecord extends EssayEvaluationRecordSummary {
  essay_text: string
  requirements: string
}

export interface EssayEvaluationListResponse {
  items: EssayEvaluationRecordSummary[]
  count: number
}

export interface EssayEvaluationCreateResponse {
  evaluation_id: number
  result: EssayEvaluationResult
}

export async function evaluateEssay(payload: EssayEvaluationRequest): Promise<EssayEvaluationCreateResponse> {
  const response = await apiClient.post<EssayEvaluationCreateResponse>('/essay-evaluations/evaluate', payload)
  return response.data
}

export async function listEssayEvaluations(params: { limit?: number; offset?: number } = {}): Promise<EssayEvaluationListResponse> {
  const response = await apiClient.get<EssayEvaluationListResponse>('/essay-evaluations', { params })
  return response.data
}

export async function getEssayEvaluation(evaluationId: number): Promise<EssayEvaluationRecord> {
  const response = await apiClient.get<EssayEvaluationRecord>(`/essay-evaluations/${evaluationId}`)
  return response.data
}

export async function deleteEssayEvaluation(evaluationId: number): Promise<{ success: boolean }> {
  const response = await apiClient.delete<{ success: boolean }>(`/essay-evaluations/${evaluationId}`)
  return response.data
}

export async function submitEssayEvaluationTask(payload: EssayEvaluationRequest): Promise<{ taskId: string }> {
  const response = await apiClient.post<{ success: boolean; taskId: string }>(
    '/tasks/essay-evaluations/evaluate',
    payload,
  )
  return { taskId: response.data.taskId }
}
