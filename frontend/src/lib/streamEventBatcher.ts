export const STREAM_EVENT_BATCH_MAX_DELAY_MS = 60

export type StreamEventBatcher<T> = {
  enqueue: (event: T) => void
  flush: () => void
  cancel: () => void
}

export function createStreamEventBatcher<T>(
  onEvent: (event: T) => void,
  options?: { maxDelayMs?: number; shouldFlushImmediately?: (event: T) => boolean }
): StreamEventBatcher<T> {
  let queue: T[] = []
  let rafId: number | null = null
  let timeoutId: ReturnType<typeof setTimeout> | null = null

  const maxDelayMs = Math.max(16, options?.maxDelayMs ?? STREAM_EVENT_BATCH_MAX_DELAY_MS)
  const shouldFlushImmediately = options?.shouldFlushImmediately

  const clearScheduled = () => {
    if (rafId !== null && typeof globalThis.cancelAnimationFrame === 'function') {
      globalThis.cancelAnimationFrame(rafId)
    }
    if (timeoutId !== null) {
      globalThis.clearTimeout(timeoutId)
    }
    rafId = null
    timeoutId = null
  }

  const flush = () => {
    clearScheduled()
    if (queue.length === 0) return

    const events = queue
    queue = []
    for (const event of events) {
      onEvent(event)
    }
  }

  const schedule = () => {
    if (rafId !== null || timeoutId !== null) return

    if (typeof globalThis.requestAnimationFrame === 'function') {
      rafId = globalThis.requestAnimationFrame(() => flush())
    }

    timeoutId = globalThis.setTimeout(() => flush(), maxDelayMs)
  }

  return {
    enqueue: (event: T) => {
      queue.push(event)
      if (shouldFlushImmediately?.(event)) {
        flush()
        return
      }
      schedule()
    },
    flush,
    cancel: () => {
      clearScheduled()
      queue = []
    },
  }
}
