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

// SSE helper for streaming responses
export function createSSEConnection(
  url: string,
  onMessage: (data: unknown) => void,
  onError?: (error: Event) => void,
  onComplete?: () => void
): EventSource {
  const fullUrl = joinBaseUrl(API_BASE_URL, url)

  // Note: EventSource doesn't support custom headers
  // For auth, we'll need to pass token as query param or use fetch-based SSE
  const eventSource = new EventSource(fullUrl)

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'done' || data.done) {
        onComplete?.()
        eventSource.close()
      } else {
        onMessage(data)
      }
    } catch {
      // Plain text message
      onMessage(event.data)
    }
  }

  eventSource.onerror = (error) => {
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
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: {
    headers?: Record<string, string>
    signal?: AbortSignal
  }
): Promise<void> {
  return fetchSSERequest(
    url,
    { method: 'POST', body, headers: options?.headers, signal: options?.signal },
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
  },
  onMessage: (data: unknown) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): Promise<void> {
  return fetchSSERequestInternal(url, options, onMessage, onError, onComplete, 0)
}

async function fetchSSERequestInternal(
  url: string,
  options: {
    method?: 'GET' | 'POST'
    body?: unknown
    headers?: Record<string, string>
    signal?: AbortSignal
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
      if (response.status === 401) {
        useAuthStore.getState().logout()
        window.location.href = '/login'
        return
      }

      const isStudyMaterials = url.startsWith('/study-materials/')
      if (isStudyMaterials && (response.status === 404 || response.status === 405)) {
        const err = await responseToApiError(response, 'backend_not_ready')
        throw new ApiError({
          ...err,
          code: 'backend_not_ready',
          message: `后端接口未就绪（${response.status}）。请停止并重启后端（运行 start.bat）后再试。`,
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
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data === '[DONE]') {
            onComplete?.()
            return
          }
          try {
            const parsed = JSON.parse(data)
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
    if ((error as any)?.name === 'AbortError') {
      onComplete?.()
      return
    }
    const normalized = isApiError(error)
      ? (error as Error)
      : new ApiError({
          code: 'network_error',
          message: (error as any)?.message || 'network_error',
          status: 0,
          requestId: undefined,
          detail: error,
          retriable: true,
        })
    onError?.(normalized)
  }
}

