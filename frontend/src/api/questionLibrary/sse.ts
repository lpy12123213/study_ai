import { apiClient, fetchSSE, fetchSSERequest } from '@/api/client'
import { streamTask } from '@/api/tasks'
import { normalizeSseEnvelope, type SseEnvelope } from '@/lib/sse'
import type {
  CrawlQuestionsPayload,
  GenerateQuestionsPayload,
  ImportMediaQuestionsPayload,
  RegenerateQuestionLibrarySectionEvent,
  RegenerateQuestionLibrarySectionPayload,
} from './types'

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
  return recordString(error, 'message') || 'request_failed'
}

type StreamOptions = {
  signal?: AbortSignal
}

export function normalizeQuestionLibraryTaskEvent(input: unknown): SseEnvelope {
  return normalizeSseEnvelope(input)
}

export function regenerateQuestionLibrarySection(
  previewId: string,
  payload: RegenerateQuestionLibrarySectionPayload,
  onEvent: (event: SseEnvelope<RegenerateQuestionLibrarySectionEvent>) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: {
    signal?: AbortSignal
  }
): void {
  const pid = String(previewId || '').trim()
  if (!pid) throw new Error('missing_preview_id')
  fetchSSE(
    `/question-library/previews/${encodeURIComponent(pid)}/regenerate-section`,
    payload,
    (data) => onEvent(normalizeQuestionLibraryTaskEvent(data) as SseEnvelope<RegenerateQuestionLibrarySectionEvent>),
    onError,
    onComplete,
    { signal: options?.signal }
  )
}

export function crawlQuestions(
  payload: CrawlQuestionsPayload,
  onEvent: (event: SseEnvelope) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: StreamOptions
): void {
  apiClient
    .post('/tasks/question-library/crawl', payload, { signal: options?.signal })
    .then((res) => {
      const taskId = String(recordString(res.data, 'taskId') || payload.task_id || '').trim()
      if (!taskId) throw new Error('missing_task_id')
      streamTask(
        taskId,
        0,
        (evt) => onEvent(normalizeQuestionLibraryTaskEvent(evt)),
        onError,
        onComplete,
        { signal: options?.signal }
      )
    })
    .catch((err: unknown) => {
      if (options?.signal?.aborted) return
      const message = errorMessage(err)
      onError?.(err instanceof Error ? err : new Error(message))
    })
}

export function generateQuestions(
  payload: GenerateQuestionsPayload,
  onEvent: (event: SseEnvelope) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: StreamOptions
): void {
  apiClient
    .post('/tasks/question-library/generate', payload, { signal: options?.signal })
    .then((res) => {
      const taskId = String(recordString(res.data, 'taskId') || payload.task_id || '').trim()
      if (!taskId) throw new Error('missing_task_id')
      streamTask(
        taskId,
        0,
        (evt) => onEvent(normalizeQuestionLibraryTaskEvent(evt)),
        onError,
        onComplete,
        { signal: options?.signal }
      )
    })
    .catch((err: unknown) => {
      if (options?.signal?.aborted) return
      const message = errorMessage(err)
      onError?.(err instanceof Error ? err : new Error(message))
    })
}

export function importMediaQuestions(
  payload: ImportMediaQuestionsPayload,
  onEvent: (event: SseEnvelope) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: StreamOptions
): void {
  const form = new FormData()
  form.set('subject', String(payload.subject || '').trim())
  form.set('topic', String(payload.topic || '').trim())
  form.set('difficulty', String(payload.difficulty || '').trim())
  form.set('question_type', String(payload.question_type || '').trim())
  form.set('count', String(Math.max(1, Math.min(30, Math.floor(Number(payload.count) || 10)))))
  form.set('max_pdf_pages', String(Math.max(1, Math.min(30, Math.floor(Number(payload.max_pdf_pages) || 12)))))
  if (payload.task_id) form.set('task_id', payload.task_id)
  for (const file of payload.files || []) {
    form.append('files', file)
  }

  apiClient
    .post('/tasks/question-library/import-media', form, { signal: options?.signal })
    .then((res) => {
      const taskId = String(recordString(res.data, 'taskId') || payload.task_id || '').trim()
      if (!taskId) throw new Error('missing_task_id')
      streamTask(
        taskId,
        0,
        (evt) => onEvent(normalizeQuestionLibraryTaskEvent(evt)),
        onError,
        onComplete,
        { signal: options?.signal }
      )
    })
    .catch((err: unknown) => {
      if (options?.signal?.aborted) return
      const message = errorMessage(err)
      onError?.(err instanceof Error ? err : new Error(message))
    })
}

export function streamQuestionLibraryTask(
  taskId: string,
  afterSeq: number,
  onEvent: (event: SseEnvelope) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: StreamOptions
): void {
  const id = String(taskId || '').trim()
  if (!id) throw new Error('missing_task_id')
  fetchSSERequest(
    `/question-library/tasks/${encodeURIComponent(id)}/stream?after_seq=${Math.max(0, afterSeq || 0)}`,
    { method: 'GET', signal: options?.signal },
    (data) => onEvent(normalizeQuestionLibraryTaskEvent(data)),
    onError,
    onComplete
  )
}
