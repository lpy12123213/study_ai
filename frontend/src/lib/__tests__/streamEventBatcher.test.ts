import { afterEach, describe, expect, it, vi } from 'vitest'
import { createStreamEventBatcher } from '@/lib/streamEventBatcher'

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
})
