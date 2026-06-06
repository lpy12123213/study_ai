import { describe, expect, it } from 'vitest'

import { normalizeChatStreamEvent } from '../sse'

describe('normalizeChatStreamEvent', () => {
  it('extracts websocket error text from nested data.error payloads', () => {
    expect(
      normalizeChatStreamEvent({
        type: 'error',
        data: { error: 'tokenizer unavailable' },
      })
    ).toMatchObject({
      type: 'error',
      error: 'tokenizer unavailable',
    })
  })
})
