export const STREAM_EVENT_BATCH_MAX_DELAY_MS = 60
export const STREAM_EVENT_BATCH_INITIAL_FLUSH_COUNT = 3
export const STREAM_EVENT_BATCH_SLOW_DELAY_MS = 120

export type StreamEventBatcher<T> = {
  enqueue: (event: T) => void
  flush: () => void
  cancel: () => void
}

type ConnectionLike = { effectiveType?: string; saveData?: boolean }

function detectInitialDelayMs(fallback: number): number {
  if (typeof globalThis === 'undefined') return fallback
  const nav = (globalThis as unknown as { navigator?: { connection?: ConnectionLike } }).navigator
  const conn = nav?.connection
  if (!conn) return fallback
  // Slow connections benefit from a larger batch window so the main thread is not
  // saturated with frequent React commits during long SSE streams.
  if (conn.saveData) return STREAM_EVENT_BATCH_SLOW_DELAY_MS
  if (conn.effectiveType && /^(slow-2g|2g|3g)$/i.test(conn.effectiveType)) {
    return STREAM_EVENT_BATCH_SLOW_DELAY_MS
  }
  return fallback
}

function detectReducedMotion(): boolean {
  if (typeof globalThis === 'undefined') return false
  const win = globalThis as unknown as { matchMedia?: (query: string) => { matches: boolean } | undefined }
  try {
    return Boolean(win.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches)
  } catch {
    return false
  }
}

export function createStreamEventBatcher<T>(
  onEvent: (event: T) => void,
  options?: { maxDelayMs?: number; shouldFlushImmediately?: (event: T) => boolean }
): StreamEventBatcher<T> {
  let queue: T[] = []
  let rafId: number | null = null
  let timeoutId: ReturnType<typeof setTimeout> | null = null

  // The first few events are flushed eagerly so users see fast first-byte feedback.
  // After the warmup window we settle into the configured throttle. Reduced-motion
  // users get the slower (calmer) cadence.
  const baseDelayMs = options?.maxDelayMs ?? STREAM_EVENT_BATCH_MAX_DELAY_MS
  const reducedMotion = detectReducedMotion()
  const adaptiveDelayMs = reducedMotion
    ? STREAM_EVENT_BATCH_SLOW_DELAY_MS
    : detectInitialDelayMs(baseDelayMs)
  const maxDelayMs = Math.max(16, adaptiveDelayMs)

  let eagerEventsRemaining = STREAM_EVENT_BATCH_INITIAL_FLUSH_COUNT
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
      // Eager first-byte path: flush immediately for the first few events so
      // users do not wait the full batch window before seeing tokens.
      if (eagerEventsRemaining > 0) {
        eagerEventsRemaining -= 1
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
