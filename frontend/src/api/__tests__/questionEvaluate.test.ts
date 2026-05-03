import { describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
import { evaluateQuestions } from '@/api/questionEvaluate'

vi.mock('@/api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
  fetchSSERequest: vi.fn(),
}))

describe('questionEvaluate api', () => {
  it('submits evaluation through the unified task API and reads the task result', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { taskId: 'qe-1' } })
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: {
        status: 'completed',
        result: {
          model: 'test-model',
          results: [
            {
              question_id: 'q1',
              verdict: '好题',
              overall_score: 88,
              dimensions: [],
              highlights: ['区分度好'],
              issues: [],
              summary: 'ok',
            },
          ],
        },
      },
    })

    const res = await evaluateQuestions({
      subject: '高中数学',
      questions: [{ questionId: 'q1', stem: '已知 f(x)=x^2，判断单调性。' }],
    })

    expect(apiClient.post).toHaveBeenCalledWith('/tasks/question-evaluate/evaluate', {
      subject: '高中数学',
      requirements: undefined,
      model: undefined,
      questions: [
        {
          question_id: 'q1',
          stem: '已知 f(x)=x^2，判断单调性。',
          type: undefined,
          difficulty: undefined,
          knowledge_points: undefined,
          source: undefined,
          source_url: undefined,
          date: undefined,
          quality_score: undefined,
          quality_flags: undefined,
          difficulty_value: undefined,
        },
      ],
    })
    expect(apiClient.get).toHaveBeenCalledWith('/tasks/qe-1', {
      params: {
        include_events: true,
        events_limit: 200,
      },
    })
    expect(res.taskId).toBe('qe-1')
    expect(res.model).toBe('test-model')
    expect(res.results[0]?.questionId).toBe('q1')
    expect(res.results[0]?.overallScore).toBe(88)
  })
})

