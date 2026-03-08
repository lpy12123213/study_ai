import { apiClient } from '@/api/client'

export type FeedbackReport = {
  id: number
  title: string
  description: string
  status: string
  context: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export async function listFeedback(limit = 50): Promise<FeedbackReport[]> {
  const res = await apiClient.get('/feedback', { params: { limit } })
  return (res.data?.feedback as FeedbackReport[]) || []
}

export async function createFeedback(input: {
  title?: string
  description: string
  context?: Record<string, unknown>
}): Promise<FeedbackReport> {
  const res = await apiClient.post('/feedback', input)
  return res.data?.feedback as FeedbackReport
}

