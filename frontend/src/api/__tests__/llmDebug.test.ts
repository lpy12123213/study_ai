import { describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
import { getLlmDebugCalls } from '@/api/llmDebug'

vi.mock('@/api/client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

describe('llmDebug api', () => {
  it('requests recent LLM calls with a bounded limit', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { calls: [] } })

    await getLlmDebugCalls({ limit: 20 })

    expect(apiClient.get).toHaveBeenCalledWith('/llm-debug', {
      params: { limit: 20 },
    })
  })
})
