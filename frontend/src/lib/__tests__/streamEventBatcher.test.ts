import {
  STREAM_EVENT_BATCH_INITIAL_FLUSH_COUNT,
  STREAM_EVENT_BATCH_MAX_DELAY_MS,
  createStreamEventBatcher,
} from '@/lib/streamEventBatcher'
import { afterEach, describe, expect, it, vi } from 'vitest'

describe('createStreamEventBatcher', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('flushes initial events eagerly, then coalesces queued events until the next animation frame', () => {
    vi.useFakeTimers()
    const frameCallbacks: FrameRequestCallback[] = []
    const requestAnimationFrameMock = vi.fn((callback: FrameRequestCallback) => {
      frameCallbacks.push(callback)
      return frameCallbacks.length
    })
    const cancelAnimationFrameMock = vi.fn()
    vi.stubGlobal('requestAnimationFrame', requestAnimationFrameMock)
    vi.stubGlobal('cancelAnimationFrame', cancelAnimationFrameMock)

    const onEvent = vi.fn()
    const batcher = createStreamEventBatcher(onEvent)

    batcher.enqueue('first')
    batcher.enqueue('second')
    batcher.enqueue('third')

    expect(onEvent.mock.calls.map(([event]) => event)).toEqual(['first', 'second', 'third'])

    batcher.enqueue('fourth')
    batcher.enqueue('fifth')

    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(1)
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual(['first', 'second', 'third'])

    frameCallbacks[0]?.(16)

    expect(onEvent.mock.calls.map(([event]) => event)).toEqual(['first', 'second', 'third', 'fourth', 'fifth'])
    expect(cancelAnimationFrameMock).toHaveBeenCalledWith(1)
  })

  it('falls back to a bounded timeout after the eager warmup when animation frames are unavailable', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestAnimationFrame', undefined)
    vi.stubGlobal('cancelAnimationFrame', undefined)

    const onEvent = vi.fn()
    const batcher = createStreamEventBatcher(onEvent, { maxDelayMs: 100 })

    batcher.enqueue(1)
    batcher.enqueue(2)
    batcher.enqueue(3)
    batcher.enqueue(4)
    batcher.enqueue(5)

    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([1, 2, 3])

    vi.advanceTimersByTime(99)
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([1, 2, 3])

    vi.advanceTimersByTime(1)
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([1, 2, 3, 4, 5])
  })

  it('flushes pending events synchronously when requested', () => {
    vi.useFakeTimers()
    const onEvent = vi.fn()
    const batcher = createStreamEventBatcher(onEvent, { maxDelayMs: 100 })

    for (let seq = 1; seq <= STREAM_EVENT_BATCH_INITIAL_FLUSH_COUNT; seq += 1) {
      batcher.enqueue({ seq })
    }
    batcher.enqueue({ seq: 4 })
    batcher.enqueue({ seq: 5 })
    batcher.flush()

    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([
      { seq: 1 },
      { seq: 2 },
      { seq: 3 },
      { seq: 4 },
      { seq: 5 },
    ])

    vi.advanceTimersByTime(100)
    expect(onEvent).toHaveBeenCalledTimes(5)
  })

  it('flushes queued events immediately for configured high-priority events after warmup', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestAnimationFrame', undefined)
    vi.stubGlobal('cancelAnimationFrame', undefined)

    const onEvent = vi.fn()
    const batcher = createStreamEventBatcher<{ type: string }>(onEvent, {
      maxDelayMs: 100,
      shouldFlushImmediately: (event) => event.type === 'tool_result',
    })

    batcher.enqueue({ type: 'warmup-1' })
    batcher.enqueue({ type: 'warmup-2' })
    batcher.enqueue({ type: 'warmup-3' })
    batcher.enqueue({ type: 'progress' })
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([
      { type: 'warmup-1' },
      { type: 'warmup-2' },
      { type: 'warmup-3' },
    ])

    batcher.enqueue({ type: 'tool_result' })
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([
      { type: 'warmup-1' },
      { type: 'warmup-2' },
      { type: 'warmup-3' },
      { type: 'progress' },
      { type: 'tool_result' },
    ])

    vi.advanceTimersByTime(100)
    expect(onEvent).toHaveBeenCalledTimes(5)
  })

  it('defaults to a 60ms bounded delay', () => {
    expect(STREAM_EVENT_BATCH_MAX_DELAY_MS).toBe(60)
  })
})
