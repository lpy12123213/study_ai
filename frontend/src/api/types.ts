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

