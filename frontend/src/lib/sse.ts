export type SseEnvelope<TData = unknown> = {
  taskId?: string
  seq?: number
  type: string
  data?: TData
}

function toOptionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed ? trimmed : undefined
}

function toOptionalNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const n = Number(value)
    if (Number.isFinite(n)) return n
  }
  return undefined
}

/**
 * Normalize various backend SSE shapes into a unified envelope:
 * `{ taskId, seq, type, data }`.
 *
 * Supported legacy shapes:
 * - study-materials (old): `{ event, data, task_id, seq }`
 * - paper-compose (old): `{ type, step|progress|result|error, taskId, seq }`
 */
export function normalizeSseEnvelope(input: unknown): SseEnvelope {
  if (!input || typeof input !== 'object') {
    return { type: 'message', data: input }
  }

  const obj = input as Record<string, unknown>
  const data =
    obj.data && typeof obj.data === 'object'
      ? (obj.data as Record<string, unknown>)
      : undefined

  const taskId =
    toOptionalString(obj.taskId) ||
    toOptionalString(obj.task_id) ||
    (data ? toOptionalString(data.taskId) || toOptionalString(data.task_id) : undefined)

  const seq = toOptionalNumber(obj.seq) ?? (data ? toOptionalNumber(data.seq) : undefined)

  let type =
    toOptionalString(obj.type) ||
    toOptionalString(obj.event) ||
    (data ? toOptionalString(data.type) || toOptionalString(data.event) : undefined) ||
    ''

  // Compose legacy payloads sometimes put the useful content at the top-level.
  let normalizedData: unknown = obj.data
  if (normalizedData === undefined) {
    const legacy: Record<string, unknown> = {}
    if (obj.step !== undefined) legacy.step = obj.step
    if (obj.progress !== undefined) legacy.progress = obj.progress
    if (obj.result !== undefined) legacy.result = obj.result
    if (obj.error !== undefined) legacy.error = obj.error
    if (obj.message !== undefined) legacy.message = obj.message
    if (Object.keys(legacy).length > 0) normalizedData = legacy
  }

  if (!type) {
    const doneFlag = obj.done ?? (data ? data.done : undefined)
    if (doneFlag) type = 'done'
  }

  if (!type) type = 'message'

  return { taskId, seq, type, data: normalizedData }
}

