import { apiClient, fetchSSE } from './client'
import type { LessonPlan, TaskStep } from '@/types'

export interface CreateLessonPlanRequest {
  subject: string
  grade: string
  topic: string
  duration?: number
  objectives?: string[]
}

export interface LessonPlanStreamEvent {
  type: 'step' | 'progress' | 'result' | 'done' | 'error'
  step?: TaskStep
  progress?: number
  result?: LessonPlan
  error?: string
}

export async function getLessonPlans(): Promise<LessonPlan[]> {
  const response = await apiClient.get<LessonPlan[]>('/lesson-plans')
  return response.data
}

export async function getLessonPlan(id: string): Promise<LessonPlan> {
  const response = await apiClient.get<LessonPlan>(`/lesson-plans/${id}`)
  return response.data
}

export function createLessonPlanStream(
  request: CreateLessonPlanRequest,
  onEvent: (event: LessonPlanStreamEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): void {
  fetchSSE(
    '/lesson-plans',
    request,
    (data) => {
      onEvent(data as LessonPlanStreamEvent)
    },
    onError,
    onComplete
  )
}

export async function createLessonPlan(
  request: CreateLessonPlanRequest
): Promise<LessonPlan> {
  const response = await apiClient.post<LessonPlan>('/lesson-plans', request)
  return response.data
}

export async function updateLessonPlan(
  id: string,
  data: Partial<LessonPlan>
): Promise<LessonPlan> {
  const response = await apiClient.patch<LessonPlan>(`/lesson-plans/${id}`, data)
  return response.data
}

export async function deleteLessonPlan(id: string): Promise<void> {
  await apiClient.delete(`/lesson-plans/${id}`)
}

export async function pauseLessonPlanTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${taskId}/pause`)
}

export async function resumeLessonPlanTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${taskId}/resume`)
}

export const lessonPlansApi = {
  getLessonPlans,
  getLessonPlan,
  createLessonPlanStream,
  createLessonPlan,
  updateLessonPlan,
  deleteLessonPlan,
  pauseLessonPlanTask,
  resumeLessonPlanTask,
  list: async (): Promise<{ data: any }> => ({
    data: { plans: await getLessonPlans() },
  }),
  get: async (id: string): Promise<{ data: any }> => ({
    data: await getLessonPlan(id),
  }),
}
