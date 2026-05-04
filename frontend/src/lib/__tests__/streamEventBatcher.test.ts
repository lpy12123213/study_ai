import { afterEach, describe, expect, it, vi } from 'vitest'
import { STREAM_EVENT_BATCH_MAX_DELAY_MS, createStreamEventBatcher } from '@/lib/streamEventBatcher'

describe('createStreamEventBatcher', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('coalesces queued events until the next animation frame', () => {
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

    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(1)
    expect(onEvent).not.toHaveBeenCalled()

    frameCallbacks[0]?.(16)

    expect(onEvent.mock.calls.map(([event]) => event)).toEqual(['first', 'second'])
    expect(cancelAnimationFrameMock).toHaveBeenCalledWith(1)
  })

  it('falls back to a bounded timeout when animation frames are unavailable', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestAnimationFrame', undefined)
    vi.stubGlobal('cancelAnimationFrame', undefined)

    const onEvent = vi.fn()
    const batcher = createStreamEventBatcher(onEvent, { maxDelayMs: 100 })

    batcher.enqueue(1)
    batcher.enqueue(2)

    vi.advanceTimersByTime(99)
    expect(onEvent).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([1, 2])
  })

  it('flushes pending events synchronously when requested', () => {
    vi.useFakeTimers()
    const onEvent = vi.fn()
    const batcher = createStreamEventBatcher(onEvent, { maxDelayMs: 100 })

    batcher.enqueue({ seq: 1 })
    batcher.enqueue({ seq: 2 })
    batcher.flush()

    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([{ seq: 1 }, { seq: 2 }])

    vi.advanceTimersByTime(100)
    expect(onEvent).toHaveBeenCalledTimes(2)
  })

  it('flushes immediately for configured high-priority events', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestAnimationFrame', undefined)
    vi.stubGlobal('cancelAnimationFrame', undefined)

    const onEvent = vi.fn()
    const batcher = createStreamEventBatcher<{ type: string }>(onEvent, {
      maxDelayMs: 100,
      shouldFlushImmediately: (event) => event.type === 'tool_result',
    })

    batcher.enqueue({ type: 'progress' })
    expect(onEvent).not.toHaveBeenCalled()

    batcher.enqueue({ type: 'tool_result' })
    expect(onEvent.mock.calls.map(([event]) => event)).toEqual([{ type: 'progress' }, { type: 'tool_result' }])

    vi.advanceTimersByTime(100)
    expect(onEvent).toHaveBeenCalledTimes(2)
  })
})
  it('defaults to a 60ms bounded delay', () => {
    expect(STREAM_EVENT_BATCH_MAX_DELAY_MS).toBe(60)
  })
