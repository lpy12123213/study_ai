import { apiClient, fetchSSERequest } from '@/api/client'

export type UnifiedTaskStatus = 'running' | 'paused' | 'completed' | 'failed' | 'canceled' | string

export type UnifiedTask = {
  id: string
  task_type: string
  title: string
  status: UnifiedTaskStatus
  progress: number
  last_seq: number
  created_at: string
  updated_at: string
  started_at?: string
  ended_at?: string
  parent_task_id?: string | null
  request?: unknown
  result?: unknown
  error?: unknown
  events?: TaskStreamEvent[]
  elapsed_s?: number
  eta_s?: number
}

export type UnifiedTaskListResponse = {
  tasks: UnifiedTask[]
  count: number
}

export type TaskStreamEvent = {
  taskId: string
  seq: number
  type: string
  data?: any
  created_at?: string
}

export async function listTasks(params?: {
  status?: string
  type?: string
  limit?: number
  offset?: number
}): Promise<UnifiedTaskListResponse> {
  const response = await apiClient.get<UnifiedTaskListResponse>('/tasks', { params })
  return response.data
}

export async function getTask(
  taskId: string,
  options?: {
    includeEvents?: boolean
    eventsLimit?: number
  }
): Promise<any> {
  const params: Record<string, unknown> = {}
  if (options?.includeEvents !== undefined) params.include_events = Boolean(options.includeEvents)
  if (options?.eventsLimit !== undefined) params.events_limit = Math.max(1, Math.floor(Number(options.eventsLimit) || 1))

  const config = Object.keys(params).length > 0 ? { params } : undefined
  const response = await apiClient.get(`/tasks/${encodeURIComponent(taskId)}`, config)
  return response.data
}

export function streamTask(
  taskId: string,
  afterSeq: number,
  onEvent: (event: TaskStreamEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: { signal?: AbortSignal }
): void {
  const encodedId = encodeURIComponent(taskId)
  fetchSSERequest(
    `/tasks/${encodedId}/stream?after_seq=${Math.max(0, afterSeq || 0)}`,
    { method: 'GET', signal: options?.signal },
    (data) => onEvent(data as TaskStreamEvent),
    onError,
    onComplete
  )
}

export async function pauseTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${encodeURIComponent(taskId)}/pause`)
}

export async function resumeTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${encodeURIComponent(taskId)}/resume`)
}

export async function cancelTask(taskId: string): Promise<void> {
  await apiClient.post(`/tasks/${encodeURIComponent(taskId)}/cancel`)
}

export async function retryTask(taskId: string): Promise<{ taskId: string }> {
  const response = await apiClient.post(`/tasks/${encodeURIComponent(taskId)}/retry`)
  return { taskId: String((response.data as any)?.taskId || '') }
}

export async function exportPaperTask(
  paperId: number | string,
  input: { format: 'markdown' | 'pdf' | 'latex' | 'tex' | 'docx'; includeStem?: boolean; includeAnswer?: boolean; includeAnalysis?: boolean }
): Promise<{ taskId: string }> {
  const res = await apiClient.post(`/tasks/export/papers/${encodeURIComponent(String(paperId))}`, {
    format: input.format,
    includeStem: Boolean(input.includeStem),
    includeAnswer: Boolean(input.includeAnswer),
    includeAnalysis: Boolean(input.includeAnalysis),
  })
  return { taskId: String((res.data as any)?.taskId || '') }
}

export async function exportStudyArchiveTask(
  archiveId: number | string,
  input: { format: 'markdown' | 'md' }
): Promise<{ taskId: string }> {
  const res = await apiClient.post(`/tasks/export/study-archives/${encodeURIComponent(String(archiveId))}`, {
    format: input.format,
  })
  return { taskId: String((res.data as any)?.taskId || '') }
}
