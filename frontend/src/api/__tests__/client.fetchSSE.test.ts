import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchSSE, isApiError } from '@/api/client'

describe('fetchSSE', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('extracts FastAPI detail into ApiError message/code for non-OK responses', async () => {
    const fetchMock: typeof fetch = async () => {
      return new Response(JSON.stringify({ detail: 'llm_not_configured' }), {
        status: 500,
        headers: { 'content-type': 'application/json' },
      })
    }
    vi.stubGlobal('fetch', fetchMock)

    const onError = vi.fn<(error: Error) => void>()

    await fetchSSE(
      '/question-library/generate',
      { subject: '高中数学', topic: 'test', count: 1 },
      () => {},
      onError
    )

    expect(onError).toHaveBeenCalledTimes(1)
    const err = onError.mock.calls[0]?.[0]
    expect(isApiError(err)).toBe(true)
    if (isApiError(err)) {
      expect(err.status).toBe(500)
      expect(err.code).toBe('llm_not_configured')
      expect(err.message).toBe('llm_not_configured')
    }
  })

  it('ignores SSE comment heartbeats and parses data lines without a required space', async () => {
    const encoder = new TextEncoder()
    const fetchMock: typeof fetch = async () => {
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode(': heartbeat\n\ndata:{"type":"done"}\n\n'))
            controller.close()
          },
        }),
        { status: 200 }
      )
    }
    vi.stubGlobal('fetch', fetchMock)

    const onMessage = vi.fn()
    const onComplete = vi.fn()

    await fetchSSE('/question-library/generate', {}, onMessage, undefined, onComplete)

    expect(onMessage).toHaveBeenCalledWith({ type: 'done' })
    expect(onComplete).toHaveBeenCalledTimes(1)
  })

  it('reports an inactivity timeout when the stream stalls', async () => {
    vi.useFakeTimers()
    const fetchMock: typeof fetch = async () => {
      return new Response(new ReadableStream(), { status: 200 })
    }
    vi.stubGlobal('fetch', fetchMock)

    const onError = vi.fn<(error: Error) => void>()
    const promise = fetchSSE('/question-library/generate', {}, () => {}, onError, undefined, {
      inactivityTimeoutMs: 10,
    })

    await vi.advanceTimersByTimeAsync(10)
    await promise

    expect(onError).toHaveBeenCalledTimes(1)
    const err = onError.mock.calls[0]?.[0]
    expect(isApiError(err)).toBe(true)
    if (isApiError(err)) {
      expect(err.code).toBe('sse_inactivity_timeout')
    }
  })

  it('reports oversized buffered SSE data before memory grows unbounded', async () => {
    const encoder = new TextEncoder()
    const fetchMock: typeof fetch = async () => {
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode(`data: ${'x'.repeat(1_000_001)}`))
            controller.close()
          },
        }),
        { status: 200 }
      )
    }
    vi.stubGlobal('fetch', fetchMock)

    const onError = vi.fn<(error: Error) => void>()
    await fetchSSE('/question-library/generate', {}, () => {}, onError)

    expect(onError).toHaveBeenCalledTimes(1)
    const err = onError.mock.calls[0]?.[0]
    expect(isApiError(err)).toBe(true)
    if (isApiError(err)) {
      expect(err.code).toBe('sse_buffer_overflow')
    }
  })
})

