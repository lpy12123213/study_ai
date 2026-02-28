import axios, { AxiosError, type AxiosInstance } from 'axios'
import { useAuthStore } from '@/stores/useAuthStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

function isAbsoluteHttpUrl(url: string): boolean {
  return /^https?:\/\//i.test(url)
}

function joinBaseUrl(base: string, path: string): string {
  const baseValue = String(base || '').trim()
  const pathValue = String(path || '').trim()

  if (!pathValue) return baseValue
  if (isAbsoluteHttpUrl(pathValue)) return pathValue

  if (isAbsoluteHttpUrl(baseValue)) {
    try {
      const baseUrl = new URL(baseValue.endsWith('/') ? baseValue : `${baseValue}/`)
      const cleaned = pathValue.startsWith('/') ? pathValue.slice(1) : pathValue
      return new URL(cleaned, baseUrl).toString()
    } catch {
      // fall through to naive join
    }
  }

  if (baseValue.endsWith('/') && pathValue.startsWith('/')) {
    return baseValue + pathValue.slice(1)
  }
  if (!baseValue.endsWith('/') && !pathValue.startsWith('/')) {
    return `${baseValue}/${pathValue}`
  }
  return `${baseValue}${pathValue}`
}

export function resolveApiResourceUrl(resourceUrl: string): string {
  const value = String(resourceUrl || '').trim()
  if (!value) return value
  if (isAbsoluteHttpUrl(value)) return value

  const baseValue = String(API_BASE_URL || '').trim()
  if (!isAbsoluteHttpUrl(baseValue)) return value

  try {
    const origin = new URL(baseValue).origin
    const path = value.startsWith('/') ? value : `/${value}`
    return new URL(path, origin).toString()
  } catch {
    return value
  }
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor - add auth token
apiClient.interceptors.request.use(
  (config) => {
    const token = useAuthStore.getState().token
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor - handle errors
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Unauthorized - clear auth state
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

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
  const fullUrl = joinBaseUrl(API_BASE_URL, url)
  const token = useAuthStore.getState().token

  const method = options.method || 'POST'
  const hasBody = options.body !== undefined && options.body !== null && method !== 'GET'

  try {
    const response = await fetch(fullUrl, {
      method,
      headers: {
        ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
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

      let detail = ''
      try {
        const contentType = response.headers.get('content-type') || ''
        if (contentType.includes('application/json')) {
          const payload = (await response.json()) as any
          detail =
            typeof payload?.detail === 'string'
              ? payload.detail
              : payload
                ? JSON.stringify(payload)
                : ''
        } else {
          detail = await response.text()
        }
      } catch {
        // ignore
      }

      const isStudyMaterials = url.startsWith('/study-materials/')
      if (isStudyMaterials && (response.status === 404 || response.status === 405)) {
        const suffix = detail ? ` (${detail})` : ''
        throw new Error(
          `后端接口未就绪（${response.status}）。请停止并重启后端（运行 start.bat）后再试。${suffix}`
        )
      }

      const suffix = detail ? ` (${detail})` : ''
      throw new Error(`HTTP error! status: ${response.status}${suffix}`)
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
    onError?.(error as Error)
  }
}
