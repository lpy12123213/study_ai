import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadBlob } from '@/api/instance'

describe('downloadBlob', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps a plain content-disposition filename with a literal percent sign', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        return new Response('ok', {
          status: 200,
          headers: {
            'content-type': 'text/plain',
            'content-disposition': 'attachment; filename="100% coverage.txt"',
          },
        })
      }),
    )

    const result = await downloadBlob('/exports/report')

    expect(result.filename).toBe('100% coverage.txt')
    expect(result.contentType).toBe('text/plain')
    expect(await result.blob.text()).toBe('ok')
  })
})
