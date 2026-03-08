import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type StickToBottomOptions = {
  thresholdPx?: number
}

export function useStickToBottom(options?: StickToBottomOptions) {
  const thresholdPx = Math.max(0, Number(options?.thresholdPx ?? 120))
  const containerRef = useRef<HTMLDivElement | null>(null)
  const shouldStickRef = useRef(true)
  const [isNearBottom, setIsNearBottom] = useState(true)

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const el = containerRef.current
    if (!el) return
    try {
      el.scrollTo({ top: el.scrollHeight, behavior })
    } catch {
      el.scrollTop = el.scrollHeight
    }
  }, [])

  const update = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const distanceToBottom = el.scrollHeight - (el.scrollTop + el.clientHeight)
    const near = distanceToBottom < thresholdPx
    shouldStickRef.current = near
    setIsNearBottom(near)
  }, [thresholdPx])

  const setShouldStick = useCallback((next: boolean) => {
    shouldStickRef.current = Boolean(next)
    setIsNearBottom(Boolean(next))
  }, [])

  const maybeStick = useCallback(() => {
    if (!shouldStickRef.current) return
    requestAnimationFrame(() => scrollToBottom('auto'))
  }, [scrollToBottom])

  useEffect(() => {
    update()
  }, [update])

  return useMemo(
    () => ({
      containerRef,
      isNearBottom,
      shouldStickRef,
      onScroll: update,
      scrollToBottom,
      maybeStick,
      setShouldStick,
    }),
    [isNearBottom, maybeStick, scrollToBottom, setShouldStick, update]
  )
}

