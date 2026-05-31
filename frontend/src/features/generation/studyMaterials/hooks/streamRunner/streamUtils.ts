import { toText } from '@/features/generation/studyMaterials/utils'
import type { TaskStep } from '@/types'
import type { StreamRecord } from '@/features/generation/studyMaterials/hooks/streamRunner/types'

/**
 * Parse `/tasks/{taskId}/stream?after_seq=N` URL.
 * Returns null if the URL is not a unified-task stream URL.
 */
export function parseTaskStreamUrl(url: string, method: string): { taskId: string; afterSeq: number } | null {
  if (method !== 'GET') return null
  const m = url.match(/^\/tasks\/([^/?#]+)\/stream(?:\?(.*))?$/)
  if (!m) return null
  const taskId = decodeURIComponent(m[1] || '')
  if (!taskId) return null
  let afterSeq = 0
  if (m[2]) {
    const params = new URLSearchParams(m[2])
    const raw = params.get('after_seq')
    if (raw) {
      const n = Number(raw)
      if (Number.isFinite(n) && n >= 0) afterSeq = Math.floor(n)
    }
  }
  return { taskId, afterSeq }
}

export function toRecord(value: unknown): StreamRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as StreamRecord
}

export function toTaskStepStatus(value: unknown, fallback: TaskStep['status']): TaskStep['status'] {
  const raw = toText(value).trim()
  return raw === 'pending' || raw === 'running' || raw === 'completed' || raw === 'failed' || raw === 'paused'
    ? raw
    : fallback
}
