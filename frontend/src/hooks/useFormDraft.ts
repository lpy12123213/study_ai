import { useEffect, useMemo, useRef } from 'react'

type DraftEnvelope<T> = {
  v: number
  updatedAt: number
  expiresAt: number
  data: T
}

function safeParseJson(value: string): unknown {
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function nowMs(): number {
  return Date.now()
}

function estimateBytes(text: string): number {
  try {
    return new TextEncoder().encode(text).length
  } catch {
    return text.length * 2
  }
}

export function useFormDraft<T>(options: {
  storageKey: string
  value: T
  enabled: boolean
  version?: number
  debounceMs?: number
  ttlMs?: number
  maxBytes?: number
  shouldSave?: (value: T) => boolean
  onRestore: (data: T) => void
}): { clearDraft: () => void } {
  const {
    storageKey,
    value,
    enabled,
    version = 1,
    debounceMs = 1500,
    ttlMs = 7 * 24 * 60 * 60 * 1000,
    maxBytes = 200_000,
    shouldSave,
    onRestore,
  } = options

  const key = useMemo(() => String(storageKey || '').trim(), [storageKey])
  const timerRef = useRef<number | null>(null)
  const restoredRef = useRef(false)

  const clearDraft = () => {
    if (!key) return
    try {
      window.localStorage.removeItem(key)
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    if (!enabled) return
    if (!key) return
    if (restoredRef.current) return
    restoredRef.current = true

    let raw = ''
    try {
      raw = String(window.localStorage.getItem(key) || '')
    } catch {
      raw = ''
    }
    if (!raw) return

    const parsed = safeParseJson(raw)
    const env = parsed as Partial<DraftEnvelope<T>>
    if (!env || typeof env !== 'object') return
    if (Number(env.v || 0) !== Number(version || 1)) {
      clearDraft()
      return
    }
    const expiresAt = Number(env.expiresAt || 0)
    if (expiresAt > 0 && expiresAt <= nowMs()) {
      clearDraft()
      return
    }
    if (!('data' in env)) {
      clearDraft()
      return
    }

    const ok = window.confirm('发现未提交草稿，是否恢复？')
    if (!ok) {
      clearDraft()
      return
    }
    onRestore(env.data as T)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key, version])

  useEffect(() => {
    if (!enabled) return
    if (!key) return

    if (timerRef.current) window.clearTimeout(timerRef.current)

    if (shouldSave && !shouldSave(value)) {
      return
    }

    timerRef.current = window.setTimeout(() => {
      try {
        const env: DraftEnvelope<T> = {
          v: Number(version || 1),
          updatedAt: nowMs(),
          expiresAt: nowMs() + Math.max(60_000, Number(ttlMs || 0)),
          data: value,
        }
        const text = JSON.stringify(env)
        if (estimateBytes(text) > Math.max(10_000, Number(maxBytes || 0))) {
          return
        }
        window.localStorage.setItem(key, text)
      } catch {
        // ignore
      }
    }, Math.max(200, Number(debounceMs || 0)))

    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current)
    }
  }, [debounceMs, enabled, key, maxBytes, shouldSave, ttlMs, value, version])

  return { clearDraft }
}

