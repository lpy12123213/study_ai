import { apiClient } from '@/api/client'

export type WrongQuestion = {
  id: number
  question_id: string
  subject: string
  knowledge_point: string
  mastery: number
  note: string
  tags: string[]
  source_ref: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export async function listWrongbook(params?: {
  subject?: string
  knowledge_point?: string
  q?: string
  limit?: number
}): Promise<WrongQuestion[]> {
  const res = await apiClient.get<{ items?: WrongQuestion[] }>('/wrongbook', { params })
  return res.data.items || []
}

export async function upsertWrongQuestion(input: {
  question_id: string
  subject?: string
  knowledge_point?: string
  mastery?: number
  note?: string
  tags?: string[]
  source_ref?: Record<string, unknown>
}): Promise<WrongQuestion> {
  const res = await apiClient.post<{ item: WrongQuestion }>('/wrongbook', input)
  return res.data.item
}

export async function deleteWrongQuestion(questionId: string): Promise<void> {
  await apiClient.delete(`/wrongbook/${encodeURIComponent(questionId)}`)
}

export async function createPracticePaper(input: {
  paper_name?: string
  question_ids?: string[]
  knowledge_point?: string
}): Promise<{ paper_id: number }> {
  const res = await apiClient.post('/wrongbook/practice', input)
  return res.data as { paper_id: number }
}

export const wrongbookApi = {
  listWrongbook,
  upsertWrongQuestion,
  deleteWrongQuestion,
  createPracticePaper,
  list: async (): Promise<{ data: { items: WrongQuestion[] } }> => ({
    data: { items: await listWrongbook({ limit: 200 }) },
  }),
}
