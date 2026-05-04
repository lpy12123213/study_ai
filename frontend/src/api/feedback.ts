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
  const res = await apiClient.get<{ feedback?: FeedbackReport[] }>('/feedback', { params: { limit } })
  return res.data.feedback || []
}

export async function createFeedback(input: {
  title?: string
  description: string
  context?: Record<string, unknown>
}): Promise<FeedbackReport> {
  const res = await apiClient.post<{ feedback: FeedbackReport }>('/feedback', input)
  return res.data.feedback
}

export const feedbackApi = {
  listFeedback,
  createFeedback,
  submit: async (input: { content?: string; description?: string; title?: string }): Promise<{ data: FeedbackReport }> => {
    const feedback = await createFeedback({
      title: input.title,
      description: String(input.description ?? input.content ?? ''),
    })
    return { data: feedback }
  },
}
