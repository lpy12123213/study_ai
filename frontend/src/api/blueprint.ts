import { LONG_TASK_CREATE_TIMEOUT_MS, apiClient, fetchSSERequest } from './client'
import type { Blueprint, BlueprintSlot, Paper, TaskStep } from '@/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object')
}

function recordString(value: unknown, key: string): string | undefined {
  if (!isRecord(value)) return undefined
  const item = value[key]
  return typeof item === 'string' ? item : undefined
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  const message = recordString(error, 'message')
  return message || 'request_failed'
}

export interface ComposeRequest {
  taskId?: string
  subject: string
  topic?: string
  paperName?: string
  mode?: 'compose' | 'fill_shortfalls' | string
  paperId?: number
  shortfalls?: Array<{
    slotIndex: number
    questionType?: string
    difficulty?: string
    requested: number
    selected: number
  }>
  slots: BlueprintSlot[]
  filters?: {
    gradeId?: number
    textbookVersion?: string
    provinceId?: number
    paperTypeId?: number
  }
  options?: {
    maxPages?: number
    perSlotExpand?: number
    minQualityScore?: number
    dedupByStem?: boolean
    avoidUsed?: boolean
    strictSlotCount?: boolean
    slotConcurrency?: number
    candidateParseContent?: boolean
    fetchDetails?: boolean
    detailsConcurrency?: number
  }
}

export interface ComposeStreamEvent {
  taskId?: string
  seq?: number
  type: 'step' | 'progress' | 'result' | 'done' | 'error' | string
  data?: {
    step?: TaskStep
    progress?: number
    result?: Paper
    error?: string
    message?: string
  } & Record<string, unknown>
}

export interface SaveBlueprintRequest {
  name: string
  subject: string
  topic?: string
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
  onComplete?: () => void,
  options?: { signal?: AbortSignal }
): void {
  apiClient
    .post('/tasks/papers/compose', request, { timeout: LONG_TASK_CREATE_TIMEOUT_MS })
    .then((res) => {
      const taskId = String(recordString(res.data, 'taskId') || request.taskId || '').trim()
      if (!taskId) throw new Error('missing_task_id')
      streamComposeTask(taskId, 0, onEvent, onError, onComplete, options)
    })
    .catch((err: unknown) => {
      const message = errorMessage(err)
      onError?.(err instanceof Error ? err : new Error(message))
    })
}

export function streamComposeTask(
  taskId: string,
  afterSeq: number,
  onEvent: (event: ComposeStreamEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: { signal?: AbortSignal }
): void {
  const encodedId = encodeURIComponent(taskId)
  fetchSSERequest(
    `/tasks/${encodedId}/stream?after_seq=${Math.max(0, afterSeq || 0)}`,
    { method: 'GET', signal: options?.signal },
    (data) => onEvent(data as ComposeStreamEvent),
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
