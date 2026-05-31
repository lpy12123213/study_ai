
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import type { Message } from '@/types'

function findLastLessEqual(sorted: number[], value: number): number {
  // Returns the largest index i such that sorted[i] <= value.
  // `sorted` is assumed to be non-decreasing.
  let lo = 0
  let hi = Math.max(0, sorted.length - 1)
  while (lo < hi) {
    const mid = Math.floor((lo + hi + 1) / 2)
    if (sorted[mid] <= value) lo = mid
    else hi = mid - 1
  }
  return lo
}

export function useVirtualMessages(options: {
  enabled?: boolean
  messages: Message[]
  containerRef: RefObject<HTMLDivElement | null>
  estimatePx?: number
  overscan?: number
}) {
  const enabled = Boolean(options.enabled)
  const { messages, containerRef } = options
  const estimatePx = Math.max(48, Number(options.estimatePx ?? 180))
  const overscan = Math.max(0, Math.floor(Number(options.overscan ?? 10)))

  const listRef = useRef<HTMLDivElement | null>(null)
  const heightsRef = useRef<Map<string, number>>(new Map())
  const observersRef = useRef<Map<string, ResizeObserver>>(new Map())
  const refCallbacksRef = useRef<Map<string, (el: HTMLDivElement | null) => void>>(new Map())

  const [measureVersion, setMeasureVersion] = useState(0)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(0)
  const [listTop, setListTop] = useState(0)

  const keys = useMemo(() => (enabled ? messages.map((m) => String(m.id)) : []), [enabled, messages])
  const indexByKey = useMemo(() => new Map(keys.map((k, i) => [k, i] as const)), [keys])

  useEffect(() => {
    if (!enabled) return
    const container = containerRef.current
    if (!container) return

    const update = () => {
      setScrollTop(container.scrollTop)
      setViewportHeight(container.clientHeight)

      const listEl = listRef.current
      if (!listEl) {
        setListTop(0)
        return
      }

      try {
        const containerRect = container.getBoundingClientRect()
        const listRect = listEl.getBoundingClientRect()
        const top = listRect.top - containerRect.top + container.scrollTop
        setListTop(top)
      } catch {
        setListTop(0)
      }
    }

    update()
    container.addEventListener('scroll', update, { passive: true })
    const ro = new ResizeObserver(() => update())
    ro.observe(container)

    return () => {
      container.removeEventListener('scroll', update)
      ro.disconnect()
    }
  }, [containerRef, enabled])

  useEffect(() => {
    return () => {
      for (const ro of observersRef.current.values()) ro.disconnect()
      observersRef.current.clear()
      refCallbacksRef.current.clear()
    }
  }, [])

  const offsets = useMemo(() => {
    const out: number[] = new Array(keys.length + 1)
    out[0] = 0
    for (let i = 0; i < keys.length; i += 1) {
      const k = keys[i]
      const h = heightsRef.current.get(k) ?? estimatePx
      out[i + 1] = out[i] + Math.max(1, h)
    }
    return out
  }, [keys, estimatePx, measureVersion])

  const totalHeight = offsets[offsets.length - 1] ?? 0

  const range = useMemo(() => {
    const n = keys.length
    if (n <= 0) return { start: 0, end: 0 }

    const topInList = Math.max(0, scrollTop - listTop)
    const bottomInList = Math.max(0, scrollTop + viewportHeight - listTop)

    const rawStart = Math.min(n - 1, findLastLessEqual(offsets, topInList))
    const rawEnd = Math.min(n - 1, findLastLessEqual(offsets, bottomInList))

    const start = Math.max(0, rawStart - overscan)
    const end = Math.min(n, rawEnd + overscan + 1)
    return { start, end }
  }, [keys.length, listTop, offsets, overscan, scrollTop, viewportHeight])

  const getMeasureRef = useCallback((key: string) => {
    const k = String(key || '').trim()
    if (!k) return () => {}

    const cached = refCallbacksRef.current.get(k)
    if (cached) return cached

    const cb = (el: HTMLDivElement | null) => {
      const existing = observersRef.current.get(k)
      if (existing) {
        existing.disconnect()
        observersRef.current.delete(k)
      }

      if (!el) return

      const measure = () => {
        try {
          const rect = el.getBoundingClientRect()
          const next = Math.max(1, Math.round(rect.height))
          const prev = heightsRef.current.get(k)
          if (prev !== next) {
            heightsRef.current.set(k, next)
            setMeasureVersion((v) => v + 1)
          }
        } catch {
          // ignore
        }
      }

      measure()
      const ro = new ResizeObserver(() => measure())
      ro.observe(el)
      observersRef.current.set(k, ro)
    }

    refCallbacksRef.current.set(k, cb)
    return cb
  }, [])

  const scrollToId = useCallback(
    (id: string, behavior: ScrollBehavior = 'smooth') => {
      const container = containerRef.current
      if (!container) return

      const key = String(id || '').trim()
      const idx = indexByKey.get(key)
      if (idx === undefined) return

      const itemTop = offsets[idx] ?? 0
      const itemBottom = offsets[idx + 1] ?? itemTop + estimatePx
      const itemHeight = Math.max(1, itemBottom - itemTop)
      const targetTop = listTop + itemTop - Math.max(0, (viewportHeight - itemHeight) / 2)

      try {
        container.scrollTo({ top: Math.max(0, targetTop), behavior })
      } catch {
        container.scrollTop = Math.max(0, targetTop)
      }
    },
    [containerRef, estimatePx, indexByKey, listTop, offsets, viewportHeight]
  )

  return {
    listRef,
    totalHeight,
    offsets,
    range,
    getMeasureRef,
    scrollToId,
  }
}
