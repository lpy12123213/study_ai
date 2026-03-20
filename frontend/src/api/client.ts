import axios, { AxiosError, type AxiosInstance } from 'axios'
import { useAuthStore } from '@/stores/useAuthStore'
import { useRequestLogStore } from '@/stores/useRequestLogStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'
const SETTINGS_API_KEY_STORAGE_KEY = 'settings_api_key'
const SETTINGS_API_KEY_ENABLED_STORAGE_KEY = 'settings_api_key_enabled'
const SETTINGS_API_KEY_DISABLED_REASON_STORAGE_KEY = 'settings_api_key_disabled_reason'

const LLM_OVERRIDE_DISABLED_CODES = new Set([
  'llm_api_key_override_disabled',
  'llm_api_key_override_forbidden',
])

export type ApiErrorAction = {
  id: string
  title: string
  request?: {
    method: 'GET' | 'POST'
    url: string
    body?: unknown
  }
}

export class ApiError extends Error {
  code: string
  status: number
  requestId?: string
  detail?: unknown
  retriable: boolean
  actions?: ApiErrorAction[]

  constructor(init: {
    code: string
    message: string
    status: number
    requestId?: string
    detail?: unknown
    retriable?: boolean
    actions?: ApiErrorAction[]
  }) {
    super(init.message)
    this.name = 'ApiError'
    this.code = init.code
    this.status = init.status
    this.requestId = init.requestId
    this.detail = init.detail
    this.retriable = Boolean(init.retriable)
    this.actions = init.actions
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

function toOptionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed ? trimmed : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function extractEnvelopeError(payload: unknown): { code?: string; message?: string; requestId?: string; actions?: ApiErrorAction[] } {
  if (!isRecord(payload)) return {}
  const err = payload.error
  if (!isRecord(err)) return {}
  const code = toOptionalString(err.code)
  const message = toOptionalString(err.message)
  const requestId = toOptionalString((err as any).request_id) || toOptionalString((err as any).requestId)
  const actionsRaw = (err as any).recommend_actions
  const actions = Array.isArray(actionsRaw)
    ? (actionsRaw
        .map((a: unknown) => {
          if (!isRecord(a)) return null
          const id = toOptionalString(a.id) || ''
          const title = toOptionalString(a.title) || ''
          if (!id || !title) return null
          const request = (a as any).request
          const parsedRequest = isRecord(request)
            ? {
                method: (toOptionalString(request.method) as 'GET' | 'POST' | undefined) || 'POST',
                url: toOptionalString(request.url) || '',
                body: (request as any).body,
              }
            : undefined
          return { id, title, request: parsedRequest?.url ? parsedRequest : undefined } satisfies ApiErrorAction
        })
        .filter(Boolean) as ApiErrorAction[])
    : undefined
  return { code, message, requestId, actions }
}

function isRetriableStatus(status: number): boolean {
  if (!Number.isFinite(status)) return false
  if (status === 408) return true
  if (status === 409) return true
  if (status === 425) return true
  if (status === 429) return true
  if (status >= 500) return true
  return false
}

async function responseToApiError(response: Response, fallbackCode: string): Promise<ApiError> {
  const status = Number(response.status || 0)
  const headerRequestId = toOptionalString(response.headers.get('X-Request-ID'))

  let detail: unknown = undefined
  let code = toOptionalString(fallbackCode) || 'http_error'
  let message = `HTTP ${status || 0}`
  let actions: ApiErrorAction[] | undefined = undefined

  try {
    const contentType = String(response.headers.get('content-type') || '')
    if (contentType.includes('application/json')) {
      const payload = (await response.json()) as unknown
      detail = payload
      const env = extractEnvelopeError(payload)
      if (env.code) code = env.code
      if (env.message) message = env.message
      if (env.actions) actions = env.actions

      // FastAPI commonly returns errors as `{ detail: "some_code" }` (or a list of validation issues).
      // Surface this as the message/code when we don't have an envelope-style `{ error: { ... } }` payload.
      if (!env.code && !env.message && isRecord(payload)) {
        const detailField = (payload as any).detail
        const detailText = toOptionalString(detailField)
        if (detailText) {
          message = detailText
          if (String(fallbackCode || '').startsWith('http_')) {
            code = detailText
          }
        } else if (Array.isArray(detailField) && detailField.length > 0) {
          const first = detailField[0]
          if (isRecord(first)) {
            const msg = toOptionalString((first as any).msg)
            if (msg) message = msg
          }
        }
      }
      const envelopeRequestId = env.requestId
      return new ApiError({
        code,
        message,
        status,
        requestId: envelopeRequestId || headerRequestId,
        detail,
        retriable: isRetriableStatus(status),
        actions,
      })
    }

    const text = await response.text()
    detail = text
    if (text.trim()) message = text.trim()
  } catch {
    // ignore parse failures
  }

  return new ApiError({
    code,
    message,
    status,
    requestId: headerRequestId,
    detail,
    retriable: isRetriableStatus(status),
    actions,
  })
}

function axiosErrorToApiError(error: AxiosError): ApiError {
  const status = Number(error.response?.status || 0)
  const payload = error.response?.data as unknown
  const env = extractEnvelopeError(payload)
  const headerRequestId =
    toOptionalString((error.response?.headers as any)?.['x-request-id']) ||
    toOptionalString((error.response?.headers as any)?.['X-Request-ID'])

  const code = env.code || (status ? `http_${status}` : 'network_error')
  const message =
    env.message ||
    (typeof (payload as any)?.detail === 'string' ? String((payload as any).detail) : '') ||
    error.message ||
    'request_failed'

  return new ApiError({
    code,
    message,
    status,
    requestId: env.requestId || headerRequestId,
    detail: payload,
    retriable: status ? isRetriableStatus(status) : true,
    actions: env.actions,
  })
}

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

function getSettingsApiKey(): string {
  try {
    if (typeof window === 'undefined') return ''
    const enabled = String(window.localStorage.getItem(SETTINGS_API_KEY_ENABLED_STORAGE_KEY) || '').trim()
    if (enabled === '0' || enabled.toLowerCase() === 'false') return ''
    return String(window.localStorage.getItem(SETTINGS_API_KEY_STORAGE_KEY) || '').trim()
  } catch {
    return ''
  }
}

function disableSettingsApiKeyOverride(reason: string): void {
  try {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(SETTINGS_API_KEY_ENABLED_STORAGE_KEY, '0')
    window.localStorage.setItem(SETTINGS_API_KEY_DISABLED_REASON_STORAGE_KEY, String(reason || 'disabled'))
  } catch {
    // ignore
  }
}

function isLlmOverrideDisabledCode(code: string): boolean {
  return LLM_OVERRIDE_DISABLED_CODES.has(String(code || '').trim())
}

function stripLlmApiKeyHeader(headers: unknown): void {
  if (!headers) return
  try {
    const h: any = headers as any
    if (typeof h.delete === 'function') {
      h.delete('X-LLM-API-Key')
      h.delete('X-Moonshot-API-Key')
      return
    }
    delete h['X-LLM-API-Key']
    delete h['X-Moonshot-API-Key']
  } catch {
    // ignore
  }
}

export function resolveApiResourceUrl(resourceUrl: string): string {
  let value = String(resourceUrl || '').trim()
  if (!value) return value
  if (isAbsoluteHttpUrl(value)) return value

  // Normalize common backend-returned paths to root-relative.
  if (!value.startsWith('/') && value.startsWith('api/')) {
    value = `/${value}`
  }

  const baseValue = String(API_BASE_URL || '').trim()

  // If base is absolute, prefer it for cross-origin deployments.
  if (isAbsoluteHttpUrl(baseValue)) {
    try {
      return joinBaseUrl(baseValue, value)
    } catch {
      // fall through
    }
  }

  // Default (same-origin) dev/prod: make it absolute using the current origin so downloads/open-in-new-tab work.
  try {
    if (typeof window !== 'undefined' && window.location?.origin) {
      const path = value.startsWith('/') ? value : joinBaseUrl(baseValue, value)
      const normalizedPath = path.startsWith('/') ? path : `/${path}`
      return new URL(normalizedPath, window.location.origin).toString()
    }
  } catch {
    // ignore
  }

  // Fallback: keep it relative.
  if (value.startsWith('/')) return value
  return joinBaseUrl(baseValue, value)
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

    const settingsApiKey = getSettingsApiKey()
    if (settingsApiKey) {
      ;(config.headers as any)['X-LLM-API-Key'] = settingsApiKey
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor - handle errors
apiClient.interceptors.response.use(
  (response) => {
    try {
      const rid = toOptionalString((response.headers as any)?.['x-request-id']) || toOptionalString((response.headers as any)?.['X-Request-ID'])
      if (rid) {
        useRequestLogStore.getState().push({
          requestId: rid,
          url: typeof (response.config as any)?.url === 'string' ? (response.config as any).url : undefined,
          status: typeof response.status === 'number' ? response.status : undefined,
        })
      }
    } catch {
      // ignore
    }
    return response
  },
  async (error: unknown) => {
    const ax = error as AxiosError
    if (ax.response?.status === 401) {
      // Unauthorized - clear auth state
      useAuthStore.getState().logout()
      window.location.href = '/login'
    }
    if (ax && typeof ax === 'object' && (ax as any).isAxiosError) {
      const apiError = axiosErrorToApiError(ax)
      try {
        if (apiError.requestId) {
          useRequestLogStore.getState().push({
            requestId: apiError.requestId,
            url: typeof (ax.config as any)?.url === 'string' ? (ax.config as any).url : undefined,
            status: apiError.status || undefined,
          })
        }
      } catch {
        // ignore
      }
      if (apiError.status === 403 && isLlmOverrideDisabledCode(apiError.code)) {
        const cfg: any = (ax as any).config
        if (cfg && !cfg.__retryWithoutLlmApiKey) {
          disableSettingsApiKeyOverride(apiError.code)
          cfg.__retryWithoutLlmApiKey = true
          stripLlmApiKeyHeader(cfg.headers)
          return apiClient.request(cfg)
        }
      }
      return Promise.reject(apiError)
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

export async function downloadText(
  resourceUrl: string,
  options?: {
    signal?: AbortSignal
    headers?: Record<string, string>
  }
): Promise<string> {
  return downloadTextInternal(resourceUrl, options, 0)
}

async function downloadTextInternal(
  resourceUrl: string,
  options: {
    signal?: AbortSignal
    headers?: Record<string, string>
  } | undefined,
  attempt: number
): Promise<string> {
  const url = resolveApiResourceUrl(resourceUrl)
  const token = useAuthStore.getState().token
  const settingsApiKey = getSettingsApiKey()

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(settingsApiKey ? { 'X-LLM-API-Key': settingsApiKey } : {}),
        ...(options?.headers || {}),
      },
      signal: options?.signal,
    })

    if (!response.ok) {
      if (response.status === 401) {
        useAuthStore.getState().logout()
        window.location.href = '/login'
        throw new ApiError({ code: 'unauthorized', message: '请重新登录', status: 401, retriable: false })
      }

      const err = await responseToApiError(response, `http_${response.status}`)
      if (response.status === 403 && isLlmOverrideDisabledCode(err.code) && attempt < 1) {
        disableSettingsApiKeyOverride(err.code)
        return downloadTextInternal(resourceUrl, options, attempt + 1)
      }

      throw err
    }

    return await response.text()
  } catch (error) {
    if (isApiError(error)) throw error
    if ((error as any)?.name === 'AbortError') throw error
    throw new ApiError({
      code: 'network_error',
      message: (error as any)?.message || 'network_error',
      status: 0,
      detail: error,
      retriable: true,
    })
  }
}

export async function downloadBlob(
  resourceUrl: string,
  options?: {
    signal?: AbortSignal
    headers?: Record<string, string>
  }
): Promise<{ blob: Blob; contentType: string; filename?: string }> {
  return downloadBlobInternal(resourceUrl, options, 0)
}

async function downloadBlobInternal(
  resourceUrl: string,
  options: {
    signal?: AbortSignal
    headers?: Record<string, string>
  } | undefined,
  attempt: number
): Promise<{ blob: Blob; contentType: string; filename?: string }> {
  const url = resolveApiResourceUrl(resourceUrl)
  const token = useAuthStore.getState().token
  const settingsApiKey = getSettingsApiKey()

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(settingsApiKey ? { 'X-LLM-API-Key': settingsApiKey } : {}),
        ...(options?.headers || {}),
      },
      signal: options?.signal,
    })

    if (!response.ok) {
      if (response.status === 401) {
        useAuthStore.getState().logout()
        window.location.href = '/login'
        throw new ApiError({ code: 'unauthorized', message: '请重新登录', status: 401, retriable: false })
      }

      const err = await responseToApiError(response, `http_${response.status}`)
      if (response.status === 403 && isLlmOverrideDisabledCode(err.code) && attempt < 1) {
        disableSettingsApiKeyOverride(err.code)
        return downloadBlobInternal(resourceUrl, options, attempt + 1)
      }

      throw err
    }

    const contentType = String(response.headers.get('content-type') || '')
    const disp = String(response.headers.get('content-disposition') || '')
    const m = disp.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i)
    const filename = m ? decodeURIComponent(m[1] || m[2] || '') : undefined

    const blob = await response.blob()
    return { blob, contentType, filename: filename || undefined }
  } catch (error) {
    if (isApiError(error)) throw error
    if ((error as any)?.name === 'AbortError') throw error
    throw new ApiError({
      code: 'network_error',
      message: (error as any)?.message || 'network_error',
      status: 0,
      detail: error,
      retriable: true,
    })
  }
}

export async function downloadObjectUrl(resourceUrl: string): Promise<{ objectUrl: string; revoke: () => void; filename?: string }> {
  const { blob, filename } = await downloadBlob(resourceUrl)
  const objectUrl = URL.createObjectURL(blob)
  const revoke = () => URL.revokeObjectURL(objectUrl)
  return { objectUrl, revoke, filename }
}
