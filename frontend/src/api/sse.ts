import { useAuthStore } from '@/stores/useAuthStore'
import { ApiError, isApiError } from '@/api/types'
import {
  API_BASE_URL,
  disableSettingsApiKeyOverride,
  getSettingsApiKey,
  isLlmOverrideDisabledCode,
  joinBaseUrl,
  responseToApiError,
} from '@/api/instance'
import { createStreamEventBatcher } from '@/lib/streamEventBatcher'

const IMMEDIATE_STREAM_EVENT_TYPES = new Set(['tool_result', 'assistant_final', 'final', 'done', 'result'])
const DEFAULT_SSE_INACTIVITY_TIMEOUT_MS = 120_000
const SSE_MAX_BUFFER_CHARS = 1_000_000

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function eventType(event: unknown): string {
  if (!isRecord(event)) return ''
  return String(event.type || event.event || '').trim()
}

function hasAbortName(value: unknown): boolean {
  return isRecord(value) && value.name === 'AbortError'
}

function errorMessage(value: unknown): string {
  return value instanceof Error ? value.message : isRecord(value) && typeof value.message === 'string' ? value.message : 'network_error'
}

function parseJsonEvent(data: string): unknown {
  return JSON.parse(data) as unknown
}

function isCompletionEvent(data: unknown): boolean {
  return isRecord(data) && (data.type === 'done' || data.done === true)
}

function shouldFlushStreamEvent(event: unknown) {
  return IMMEDIATE_STREAM_EVENT_TYPES.has(eventType(event))
}

// SSE helper for streaming responses
export function createSSEConnection(
  url: string,
  onMessage: (data: unknown) => void,
  onError?: (error: Event) => void,
  onComplete?: () => void
): EventSource {
  const fullUrl = joinBaseUrl(API_BASE_URL, url)
  const messageBatcher = createStreamEventBatcher(onMessage, { shouldFlushImmediately: shouldFlushStreamEvent })

  // Note: EventSource doesn't support custom headers
  // For auth, we'll need to pass token as query param or use fetch-based SSE
  const eventSource = new EventSource(fullUrl)
  const closeEventSource = eventSource.close.bind(eventSource)

  eventSource.close = () => {
    messageBatcher.flush()
    closeEventSource()
  }

  eventSource.onmessage = (event) => {
    try {
      const data = parseJsonEvent(event.data)
      if (isCompletionEvent(data)) {
        messageBatcher.flush()
        onComplete?.()
        eventSource.close()
      } else {
        messageBatcher.enqueue(data)
      }
    } catch {
      // Plain text message
      messageBatcher.enqueue(event.data)
    }
  }

  eventSource.onerror = (error) => {
    messageBatcher.flush()
    onError?.(error)
    eventSource.close()
  }

  return eventSource
}

// Fetch-based SSE for POST requests with body
export async function fetchSSE(
  url: string,
  body: unknown,
  onMessage: (data: unknown) => void,
  signal?: AbortSignal
): Promise<void>

export async function fetchSSE(
  url: string,
  body: unknown,
  onMessage: (data: unknown) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: {
    headers?: Record<string, string>
    signal?: AbortSignal
    inactivityTimeoutMs?: number
  }
): Promise<void>

export async function fetchSSE(
  url: string,
  body: unknown,
  onMessage: (data: unknown) => void,
  onErrorOrSignal?: ((error: Error) => void) | AbortSignal,
  onComplete?: () => void,
  options?: {
    headers?: Record<string, string>
    signal?: AbortSignal
    inactivityTimeoutMs?: number
  }
): Promise<void> {
  const signal =
    typeof AbortSignal !== 'undefined' && onErrorOrSignal instanceof AbortSignal
      ? onErrorOrSignal
      : options?.signal
  const onError = typeof onErrorOrSignal === 'function' ? onErrorOrSignal : undefined
  return fetchSSERequest(
    url,
    { method: 'POST', body, headers: options?.headers, signal, inactivityTimeoutMs: options?.inactivityTimeoutMs },
    onMessage,
    onError,
    onComplete
  )
}

export async function fetchSSERequest(
  url: string,
  options: {
    method?: 'GET' | 'POST'
    body?: unknown
    headers?: Record<string, string>
    signal?: AbortSignal
    inactivityTimeoutMs?: number
  },
  onMessage: (data: unknown) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): Promise<void> {
  const messageBatcher = createStreamEventBatcher(onMessage, { shouldFlushImmediately: shouldFlushStreamEvent })
  return fetchSSERequestInternal(
    url,
    options,
    messageBatcher.enqueue,
    (error) => {
      messageBatcher.flush()
      onError?.(error)
    },
    () => {
      messageBatcher.flush()
      onComplete?.()
    },
    0
  )
}

async function fetchSSERequestInternal(
  url: string,
  options: {
    method?: 'GET' | 'POST'
    body?: unknown
    headers?: Record<string, string>
    signal?: AbortSignal
    inactivityTimeoutMs?: number
  },
  onMessage: (data: unknown) => void,
  onError: ((error: Error) => void) | undefined,
  onComplete: (() => void) | undefined,
  attempt: number
): Promise<void> {
  const fullUrl = joinBaseUrl(API_BASE_URL, url)
  const token = useAuthStore.getState().token
  const settingsApiKey = getSettingsApiKey()

  const method = options.method || 'POST'
  const hasBody = options.body !== undefined && options.body !== null && method !== 'GET'
  const inactivityTimeoutMs = Math.max(
    1,
    Math.floor(Number(options.inactivityTimeoutMs ?? DEFAULT_SSE_INACTIVITY_TIMEOUT_MS) || DEFAULT_SSE_INACTIVITY_TIMEOUT_MS)
  )

  const readWithTimeout = async (reader: ReadableStreamDefaultReader<Uint8Array>) => {
    let timeoutId: ReturnType<typeof setTimeout> | null = null
    try {
      return await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => {
          timeoutId = globalThis.setTimeout(() => {
            reject(
              new ApiError({
                code: 'sse_inactivity_timeout',
                message: 'SSE connection timed out waiting for data',
                status: 0,
                retriable: true,
              })
            )
          }, inactivityTimeoutMs)
        }),
      ])
    } finally {
      if (timeoutId !== null) globalThis.clearTimeout(timeoutId)
    }
  }

  try {
    const response = await fetch(fullUrl, {
      method,
      headers: {
        ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(settingsApiKey ? { 'X-LLM-API-Key': settingsApiKey } : {}),
        ...(options.headers || {}),
      },
      ...(hasBody ? { body: JSON.stringify(options.body) } : {}),
      signal: options.signal,
    })

    if (!response.ok) {
      const isStudyMaterials = url.startsWith('/study-materials/')
      if (isStudyMaterials && (response.status === 404 || response.status === 405)) {
        const err = await responseToApiError(response, 'backend_not_ready')
        throw new ApiError({
          ...err,
          code: 'backend_not_ready',
          message: `本地服务未就绪（${response.status}）。请重启本地服务后再试。`,
          retriable: true,
        })
      }

      const err = await responseToApiError(response, `http_${response.status}`)
      if (response.status === 403 && isLlmOverrideDisabledCode(err.code) && attempt < 1) {
        disableSettingsApiKeyOverride(err.code)
        return fetchSSERequestInternal(
          url,
          { ...options, headers: { ...(options.headers || {}) } },
          onMessage,
          onError,
          onComplete,
          attempt + 1
        )
      }
      throw err
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await readWithTimeout(reader)
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      if (buffer.length > SSE_MAX_BUFFER_CHARS) {
        throw new ApiError({
          code: 'sse_buffer_overflow',
          message: 'SSE buffer exceeded 1MB before a complete event was received',
          status: 0,
          retriable: true,
        })
      }
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const rawLine of lines) {
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
        if (!line || line.startsWith(':')) {
          continue
        }
        if (line.startsWith('data:')) {
          const data = line.slice(5).trimStart()
          if (data === '[DONE]') {
            onComplete?.()
            return
          }
          try {
            const parsed = parseJsonEvent(data)
            onMessage(parsed)
          } catch {
            onMessage(data)
          }
        }
      }
    }

    onComplete?.()
  } catch (error) {
    // Abort is not an "error" for UX purposes.
    if (hasAbortName(error)) {
      onComplete?.()
      return
    }
    const normalized = isApiError(error)
      ? (error as Error)
      : new ApiError({
          code: 'network_error',
          message: errorMessage(error),
          status: 0,
          requestId: undefined,
          detail: error,
          retriable: true,
        })
    onError?.(normalized)
  }
}
