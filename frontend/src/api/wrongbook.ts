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
  ease_factor?: number
  interval_days?: number
  repetitions?: number
  next_review_at?: string
  last_reviewed_at?: string
  created_at?: string
  updated_at?: string
}

export type ReviewRating = 'again' | 'hard' | 'good' | 'easy'

export type ReviewQuestionContent = {
  question_id?: string
  subject?: string
  question_type?: string
  difficulty?: string
  knowledge_point?: string
  stem?: string
  answer?: string
  analysis?: string
  source?: string
  date?: string
}

export type ReviewQueueItem = WrongQuestion & {
  question?: ReviewQuestionContent
}

export type ReviewQueueResponse = {
  items: ReviewQueueItem[]
  due_count: number
  total: number
}

export type MasteryBucket = {
  subject: string
  knowledge_point?: string
  count: number
  avg_mastery: number
  min_mastery: number
  due_count: number
}

export type MasteryResponse = {
  subjects: MasteryBucket[]
  knowledge_points: MasteryBucket[]
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

export async function getReviewQueue(params?: {
  subject?: string
  limit?: number
}): Promise<ReviewQueueResponse> {
  const res = await apiClient.get<ReviewQueueResponse>('/wrongbook/review/queue', { params })
  return {
    items: res.data.items || [],
    due_count: Number(res.data.due_count || 0),
    total: Number(res.data.total || res.data.due_count || 0),
  }
}

export async function recordReview(questionId: string, rating: ReviewRating): Promise<ReviewQueueItem> {
  const res = await apiClient.post<{ item: ReviewQueueItem }>(
    `/wrongbook/review/${encodeURIComponent(questionId)}`,
    { rating },
  )
  return res.data.item
}

export async function getMastery(params?: { subject?: string }): Promise<MasteryResponse> {
  const res = await apiClient.get<MasteryResponse>('/wrongbook/mastery', { params })
  return {
    subjects: res.data.subjects || [],
    knowledge_points: res.data.knowledge_points || [],
  }
}

export const wrongbookApi = {
  listWrongbook,
  upsertWrongQuestion,
  deleteWrongQuestion,
  createPracticePaper,
  getReviewQueue,
  recordReview,
  getMastery,
  list: async (): Promise<{ data: { items: WrongQuestion[] } }> => ({
    data: { items: await listWrongbook({ limit: 200 }) },
  }),
}
