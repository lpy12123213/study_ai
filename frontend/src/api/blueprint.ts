import { apiClient, fetchSSE } from './client'
import type { Blueprint, BlueprintSlot, Paper, TaskStep } from '@/types'

export interface ComposeRequest {
  subject: string
  slots: BlueprintSlot[]
  filters?: {
    gradeId?: number
    textbookVersion?: string
    provinceId?: number
    paperTypeId?: number
  }
}

export interface ComposeStreamEvent {
  type: 'step' | 'progress' | 'result' | 'done' | 'error'
  step?: TaskStep
  progress?: number
  result?: Paper
  error?: string
}

export interface SaveBlueprintRequest {
  name: string
  subject: string
  slots: BlueprintSlot[]
}

export async function getBlueprints(): Promise<Blueprint[]> {
  const response = await apiClient.get<Blueprint[]>('/blueprints')
  return response.data
}

export async function getBlueprint(id: string): Promise<Blueprint> {
  const response = await apiClient.get<Blueprint>(`/blueprints/${id}`)
  return response.data
}

export async function saveBlueprint(
  data: SaveBlueprintRequest
): Promise<Blueprint> {
  const response = await apiClient.post<Blueprint>('/blueprints', data)
  return response.data
}

export async function deleteBlueprint(id: string): Promise<void> {
  await apiClient.delete(`/blueprints/${id}`)
}

export function composePaperStream(
  request: ComposeRequest,
  onEvent: (event: ComposeStreamEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): void {
  fetchSSE(
    '/papers/compose',
    request,
    (data) => {
      onEvent(data as ComposeStreamEvent)
    },
    onError,
    onComplete
  )
}

export async function composePaper(request: ComposeRequest): Promise<Paper> {
  const response = await apiClient.post<Paper>('/papers/compose', request)
  return response.data
}

export async function pauseComposeTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${taskId}/pause`)
}

export async function resumeComposeTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${taskId}/resume`)
}

export async function getComposeTaskStatus(taskId: string): Promise<{
  status: string
  progress: number
  steps: TaskStep[]
}> {
  const response = await apiClient.get(`/tasks/${taskId}`)
  return response.data
}
