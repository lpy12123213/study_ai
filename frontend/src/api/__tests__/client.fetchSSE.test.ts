import { describe, expect, it, vi } from 'vitest'
import { fetchSSE, isApiError } from '@/api/client'

describe('fetchSSE', () => {
  it('extracts FastAPI detail into ApiError message/code for non-OK responses', async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(JSON.stringify({ detail: 'llm_not_configured' }), {
        status: 500,
        headers: { 'content-type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock as any)

    const onError = vi.fn()

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

    vi.unstubAllGlobals()
  })
})

