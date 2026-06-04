import axios, { AxiosError, type AxiosInstance } from 'axios'
import { useAuthStore } from '@/stores/useAuthStore'
import { useRequestLogStore } from '@/stores/useRequestLogStore'
import { ApiError, type ApiErrorAction } from '@/api/types'

const viteApiBaseUrl = typeof import.meta.env.VITE_API_BASE_URL === 'string' ? import.meta.env.VITE_API_BASE_URL : ''
export const API_BASE_URL = viteApiBaseUrl || '/api'

const SETTINGS_API_KEY_STORAGE_KEY = 'settings_api_key'
const SETTINGS_API_KEY_ENABLED_STORAGE_KEY = 'settings_api_key_enabled'
const SETTINGS_API_KEY_DISABLED_REASON_STORAGE_KEY = 'settings_api_key_disabled_reason'

const LLM_OVERRIDE_DISABLED_CODES = new Set(['llm_api_key_override_disabled', 'llm_api_key_override_forbidden'])

function toOptionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed ? trimmed : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function isUnknownArray(value: unknown): value is unknown[] {
  return Array.isArray(value)
}

function recordValue(value: unknown, key: string): unknown {
  return isRecord(value) ? value[key] : undefined
}

function optionalRecord(value: unknown): Record<string, unknown> | undefined {
  return isRecord(value) ? value : undefined
}

function hasAbortName(value: unknown): boolean {
  return isRecord(value) && value.name === 'AbortError'
}

function errorMessage(value: unknown): string {
  return value instanceof Error ? value.message : toOptionalString(recordValue(value, 'message')) || 'network_error'
}

function headerValue(headers: unknown, name: string): string | undefined {
  if (!headers) return undefined
  const getter = recordValue(headers, 'get')
  if (typeof getter === 'function') {
    try {
      return toOptionalString(getter.call(headers, name))
    } catch {
      return undefined
    }
  }
  return toOptionalString(recordValue(headers, name))
}

function extractEnvelopeError(payload: unknown): {
  code?: string
  message?: string
  requestId?: string
  actions?: ApiErrorAction[]
} {
  if (!isRecord(payload)) return {}
  const err = payload.error
  if (!isRecord(err)) return {}
  const code = toOptionalString(err.code)
  const message = toOptionalString(err.message)
  const requestId = toOptionalString(err.request_id) || toOptionalString(err.requestId)
  const actionsRaw = err.recommend_actions
  const actions = Array.isArray(actionsRaw)
    ? (actionsRaw
        .map((a: unknown) => {
          if (!isRecord(a)) return null
          const id = toOptionalString(a.id) || ''
          const title = toOptionalString(a.title) || ''
          if (!id || !title) return null
          const request = a.request
          const parsedRequest = isRecord(request)
            ? {
                method: (toOptionalString(request.method) as 'GET' | 'POST' | undefined) || 'POST',
                url: toOptionalString(request.url) || '',
                body: request.body,
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

export async function responseToApiError(response: Response, fallbackCode: string): Promise<ApiError> {
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
        const detailField = payload.detail
        const detailText = toOptionalString(detailField)
        if (detailText) {
          message = detailText
          if (String(fallbackCode || '').startsWith('http_')) {
            code = detailText
          }
        } else if (isUnknownArray(detailField) && detailField.length > 0) {
          const first = detailField[0]
          if (isRecord(first)) {
            const msg = toOptionalString(first.msg)
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
  const headerRequestId = headerValue(error.response?.headers, 'x-request-id') || headerValue(error.response?.headers, 'X-Request-ID')

  const code = env.code || (status ? `http_${status}` : 'network_error')
  const message =
    env.message ||
    (typeof recordValue(payload, 'detail') === 'string' ? String(recordValue(payload, 'detail')) : '') ||
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

export function joinBaseUrl(base: string, path: string): string {
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

export function getSettingsApiKey(): string {
  try {
    if (typeof window === 'undefined') return ''
    const enabled = String(window.localStorage.getItem(SETTINGS_API_KEY_ENABLED_STORAGE_KEY) || '').trim()
    if (enabled === '0' || enabled.toLowerCase() === 'false') return ''
    return String(window.localStorage.getItem(SETTINGS_API_KEY_STORAGE_KEY) || '').trim()
  } catch {
    return ''
  }
}

export function disableSettingsApiKeyOverride(reason: string): void {
  try {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(SETTINGS_API_KEY_ENABLED_STORAGE_KEY, '0')
    window.localStorage.setItem(SETTINGS_API_KEY_DISABLED_REASON_STORAGE_KEY, String(reason || 'disabled'))
  } catch {
    // ignore
  }
}

export function isLlmOverrideDisabledCode(code: string): boolean {
  return LLM_OVERRIDE_DISABLED_CODES.has(String(code || '').trim())
}

function stripLlmApiKeyHeader(headers: unknown): void {
  if (!headers) return
  try {
    const h = optionalRecord(headers)
    const deleter = recordValue(headers, 'delete')
    if (typeof deleter === 'function') {
      deleter.call(headers, 'X-LLM-API-Key')
      deleter.call(headers, 'X-Moonshot-API-Key')
      return
    }
    if (!h) return
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

export const DEFAULT_API_TIMEOUT_MS = 30_000
export const LONG_TASK_CREATE_TIMEOUT_MS = 120_000

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: DEFAULT_API_TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
})

function resetLocalSessionAfterUnauthorized(): void {
  useAuthStore.getState().clearAuth()
}

// Request interceptor - add auth token
apiClient.interceptors.request.use(
  (config) => {
    const token = useAuthStore.getState().token
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }

    const settingsApiKey = getSettingsApiKey()
    if (settingsApiKey) {
      config.headers.set?.('X-LLM-API-Key', settingsApiKey)
      if (!config.headers.set) {
        const headers = optionalRecord(config.headers)
        if (headers) headers['X-LLM-API-Key'] = settingsApiKey
      }
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor - handle errors
apiClient.interceptors.response.use(
  (response) => {
    try {
      const rid = headerValue(response.headers, 'x-request-id') || headerValue(response.headers, 'X-Request-ID')
      if (rid) {
        useRequestLogStore.getState().push({
          requestId: rid,
          url: typeof response.config?.url === 'string' ? response.config.url : undefined,
          status: typeof response.status === 'number' ? response.status : undefined,
        })
      }
    } catch {
      // ignore
    }
    return response
  },
  async (error: unknown) => {
    if (axios.isAxiosError(error)) {
      const ax = error
      const apiError = axiosErrorToApiError(ax)
      try {
        if (apiError.requestId) {
          useRequestLogStore.getState().push({
            requestId: apiError.requestId,
            url: typeof ax.config?.url === 'string' ? ax.config.url : undefined,
            status: apiError.status || undefined,
          })
        }
      } catch {
        // ignore
      }
      if (apiError.status === 403 && isLlmOverrideDisabledCode(apiError.code)) {
        const cfg = ax.config
        const retryConfig = cfg as (typeof cfg & { __retryWithoutLlmApiKey?: boolean }) | undefined
        if (retryConfig && !retryConfig.__retryWithoutLlmApiKey) {
          disableSettingsApiKeyOverride(apiError.code)
          retryConfig.__retryWithoutLlmApiKey = true
          stripLlmApiKeyHeader(retryConfig.headers)
          return apiClient.request(retryConfig)
        }
      }
      if (apiError.status === 401) {
        resetLocalSessionAfterUnauthorized()
      }
      return Promise.reject(apiError)
    }
    return Promise.reject(error)
  }
)

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
      const err = await responseToApiError(response, `http_${response.status}`)
      if (response.status === 401) {
        resetLocalSessionAfterUnauthorized()
      }
      if (response.status === 403 && isLlmOverrideDisabledCode(err.code) && attempt < 1) {
        disableSettingsApiKeyOverride(err.code)
        return downloadTextInternal(resourceUrl, options, attempt + 1)
      }

      throw err
    }

    return await response.text()
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (hasAbortName(error)) throw error
    throw new ApiError({
      code: 'network_error',
      message: errorMessage(error),
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
      const err = await responseToApiError(response, `http_${response.status}`)
      if (response.status === 401) {
        resetLocalSessionAfterUnauthorized()
      }
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
    if (error instanceof ApiError) throw error
    if (hasAbortName(error)) throw error
    throw new ApiError({
      code: 'network_error',
      message: errorMessage(error),
      status: 0,
      detail: error,
      retriable: true,
    })
  }
}

export async function downloadObjectUrl(
  resourceUrl: string
): Promise<{ objectUrl: string; revoke: () => void; filename?: string }> {
  const { blob, filename } = await downloadBlob(resourceUrl)
  const objectUrl = URL.createObjectURL(blob)
  const revoke = () => URL.revokeObjectURL(objectUrl)
  return { objectUrl, revoke, filename }
}
