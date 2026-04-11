import { describe, expect, it } from 'vitest'
import { humanizeAiGenerateTaskError } from '@/features/aiGenerate/humanizeTaskError'

describe('humanizeAiGenerateTaskError', () => {
  it('keeps known business errors readable', () => {
    expect(humanizeAiGenerateTaskError('no_questions_generated')).toEqual({
      display: '没有生成可用题目，可能约束过多或被判题筛掉；建议简化任务描述或降低难度后重试。',
      code: 'no_questions_generated',
    })
  })

  it('humanizes provider-model mismatch request failures', () => {
    const result = humanizeAiGenerateTaskError(
      'llm_request_failed status=404 model=Pro/moonshotai/Kimi-K2.5 provider=fireworks msg=Model not found, inaccessible, and/or not deployed'
    )

    expect(result.code).toBe('llm_request_failed')
    expect(result.display).toContain('fireworks')
    expect(result.display).toContain('Pro/moonshotai/Kimi-K2.5')
    expect(result.display).toContain('模型')
    expect(result.display).toContain('配置')
  })
})
