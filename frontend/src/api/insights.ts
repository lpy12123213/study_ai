import { apiClient, downloadBlob } from '@/api/client'

export type InsightsParams = {
  days?: number
  from?: string
  to?: string
  subject?: string
}

export type TrendPoint = {
  date: string
  score_ratio: number
  count: number
}

export type ExamInsights = {
  total_sessions: number
  avg_score_ratio: number
  trend: TrendPoint[]
  objective: { correct: number; total: number; ratio: number }
  subjective: { score: number; max_score: number; ratio: number }
  accuracy_by_type: Array<{ question_type: string; correct: number; total: number; ratio: number }>
  recent: Array<{ session_id: string; paper_name: string; score_ratio: number; submitted_at?: string | null }>
}

export type EssayInsights = {
  total: number
  avg_score_ratio: number
  trend: TrendPoint[]
  by_type: Array<{ essay_type: string; score_ratio: number; count: number }>
}

export type WrongbookInsights = {
  total: number
  mastery_distribution: Array<{ bucket: string; label: string; count: number }>
  weak_points: Array<{ knowledge_point: string; avg_mastery: number; count: number }>
}

export type ActivityInsights = {
  active_days: number
  current_streak: number
  plan_completion: { completed: number; total: number; overdue: number; ratio: number }
}

export type InsightsOverview = {
  from: string
  to: string
  subject: string
  exams: ExamInsights
  essays: EssayInsights
  wrongbook: WrongbookInsights
  activity: ActivityInsights
}

function toParams(params?: InsightsParams): InsightsParams {
  return {
    ...(params?.days != null ? { days: params.days } : {}),
    ...(params?.from ? { from: params.from } : {}),
    ...(params?.to ? { to: params.to } : {}),
    ...(params?.subject?.trim() ? { subject: params.subject.trim() } : {}),
  }
}

function toQueryString(params?: InsightsParams): string {
  const qs = new URLSearchParams()
  const normalized = toParams(params)
  if (normalized.days != null) qs.set('days', String(normalized.days))
  if (normalized.from) qs.set('from', normalized.from)
  if (normalized.to) qs.set('to', normalized.to)
  if (normalized.subject) qs.set('subject', normalized.subject)
  return qs.toString()
}

export async function getInsightsOverview(params?: InsightsParams): Promise<InsightsOverview> {
  const res = await apiClient.get('/insights/overview', { params: toParams(params) })
  return res.data as InsightsOverview
}

export async function downloadInsightsCsv(params?: InsightsParams): Promise<{ blob: Blob; filename?: string }> {
  const q = toQueryString(params)
  const { blob, filename } = await downloadBlob(`/insights/export${q ? `?${q}` : ''}`)
  return { blob, filename }
}

export const insightsApi = {
  getInsightsOverview,
  downloadInsightsCsv,
}
