import { apiClient } from '@/api/client'

export type LearningPlanItem = {
  id: number
  title: string
  description: string
  due_at?: string
  completed: boolean
  completed_at?: string
  sort_order: number
  source_ref: Record<string, unknown>
}

export type LearningPlan = {
  id: number
  title: string
  archived: boolean
  created_at?: string
  updated_at?: string
  items?: LearningPlanItem[]
}

export async function listLearningPlans(params?: { include_archived?: boolean; limit?: number }): Promise<LearningPlan[]> {
  const res = await apiClient.get('/learning-plans', { params })
  return (res.data?.plans as LearningPlan[]) || []
}

export async function getLearningPlan(planId: number): Promise<LearningPlan> {
  const res = await apiClient.get(`/learning-plans/${planId}`)
  return res.data?.plan as LearningPlan
}

export async function createLearningPlan(input: { title: string; items: Array<Partial<LearningPlanItem>> }): Promise<LearningPlan> {
  const res = await apiClient.post('/learning-plans', input)
  return res.data?.plan as LearningPlan
}

export async function setLearningPlanItemCompleted(itemId: number, completed: boolean): Promise<void> {
  await apiClient.post(`/learning-plans/items/${itemId}/completed`, { completed })
}

export async function createLearningPlanFromStudyArchive(archiveId: number, input?: { title?: string }): Promise<LearningPlan> {
  const res = await apiClient.post(`/learning-plans/from-study-archive/${archiveId}`, input || {})
  return res.data?.plan as LearningPlan
}

