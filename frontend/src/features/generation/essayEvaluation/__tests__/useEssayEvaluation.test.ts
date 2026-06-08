import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'

import { useEssayEvaluation } from '../useEssayEvaluation'

vi.mock('@/api/essayEvaluations', () => ({
  evaluateEssay: vi.fn(),
  getEssayEvaluation: vi.fn(),
}))

import { evaluateEssay, getEssayEvaluation } from '@/api/essayEvaluations'

describe('useEssayEvaluation', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('persists the result + evaluation id on success', async () => {
    const mockResult = {
      score_total: 48.5,
      score_max: 60,
      grade: '良好',
      summary: '总体不错',
      strengths: ['立意清晰'],
      weaknesses: ['论据偏少'],
      suggestions: ['增加例子'],
      scores: [],
      paragraph_feedback: [],
      rewrite: '',
      model: 'mock',
      language: 'zh' as const,
      essay_type: 'argumentative' as const,
      grade_band: 'senior' as const,
    }
    vi.mocked(evaluateEssay).mockResolvedValueOnce({ evaluation_id: 42, result: mockResult })

    const { result } = renderHook(() => useEssayEvaluation())

    expect(result.current.loading).toBe(false)
    expect(result.current.result).toBeNull()

    await act(async () => {
      await result.current.evaluate({
        text: '这是一段不少于十个字的测试作文内容。',
      })
    })

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })
    expect(result.current.result).toEqual(mockResult)
    expect(result.current.evaluationId).toBe(42)
    expect(result.current.essayText).toBe('这是一段不少于十个字的测试作文内容。')
    expect(result.current.error).toBeNull()
  })

  it('loads full historical records into the active result', async () => {
    vi.mocked(getEssayEvaluation).mockResolvedValueOnce({
      id: 7,
      user_id: 'local-user',
      subject: '语文',
      topic: '成长',
      essay_type: 'argumentative',
      grade_band: 'senior',
      language: 'zh',
      score_total: 52,
      score_max: 60,
      grade: '优秀',
      scores: [],
      summary: '历史记录已加载',
      strengths: ['结构清晰'],
      weaknesses: [],
      suggestions: ['补充细节'],
      paragraph_feedback: [],
      rewrite: '',
      model: 'mock',
      created_at: '2026-06-08T10:00:00+08:00',
      updated_at: '2026-06-08T10:00:00+08:00',
      essay_text: '第一段。\n\n第二段。',
      requirements: '',
    })

    const { result } = renderHook(() => useEssayEvaluation())

    await act(async () => {
      await result.current.loadEvaluation(7)
    })

    expect(result.current.evaluationId).toBe(7)
    expect(result.current.essayText).toBe('第一段。\n\n第二段。')
    expect(result.current.result?.summary).toBe('历史记录已加载')
  })

  it('captures error message on failure', async () => {
    vi.mocked(evaluateEssay).mockRejectedValueOnce(new Error('boom'))

    const { result } = renderHook(() => useEssayEvaluation())

    await act(async () => {
      try {
        await result.current.evaluate({ text: '足够长的中文输入' })
      } catch {
        // expected
      }
    })

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })
    expect(result.current.error).toBe('boom')
    expect(result.current.result).toBeNull()
  })

  it('reset clears error / result / evaluationId', async () => {
    const { result } = renderHook(() => useEssayEvaluation())

    await act(async () => {
      result.current.reset()
    })

    expect(result.current.error).toBeNull()
    expect(result.current.result).toBeNull()
    expect(result.current.evaluationId).toBeNull()
    expect(result.current.essayText).toBe('')
  })
})
