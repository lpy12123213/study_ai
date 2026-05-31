import { apiClient } from '@/api/client'

export type LlmDebugUsage = {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_tokens?: number
  cost_usd: number
}

export type LlmDebugCall = {
  ts_s: number
  provider: string
  model: string
  tier: string
  status: string
  mode: string
  stream: boolean
  finish_reason: string
  request_id: string
  elapsed_s: number | null
  usage: LlmDebugUsage
}

export type LlmDebugResponse = {
  limit: number
  count: number
  totals: LlmDebugUsage
  by_model: Record<string, { requests: number; total_tokens: number; cached_tokens?: number; cost_usd: number }>
  calls: LlmDebugCall[]
}

export async function getLlmDebugCalls(options?: { limit?: number }): Promise<LlmDebugResponse> {
  const limit = Math.max(1, Math.min(Number(options?.limit || 20), 200))
  const res = await apiClient.get('/llm-debug', {
    params: { limit },
  })
  return res.data as LlmDebugResponse
}
