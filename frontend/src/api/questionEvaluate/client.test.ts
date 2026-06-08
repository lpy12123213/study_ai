import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
import { getTask } from '@/api/tasks'
import { evaluateQuestions } from '@/api/questionEvaluate/client'

vi.mock('@/api/client', () => ({
  apiClient: {
    post: vi.fn(),
  },
}))

vi.mock('@/api/tasks', () => ({
  getTask: vi.fn(),
}))

describe('evaluateQuestions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
  })

  it('stops polling when the caller aborts', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { taskId: 'eval-1' } })
    vi.mocked(getTask).mockResolvedValue({
      id: 'eval-1',
      status: 'running',
      progress: 10,
      task_type: 'question_evaluate',
      title: '好题鉴别',
      last_seq: 0,
      created_at: '',
      updated_at: '',
    } as any)

    const controller = new AbortController()
    const promise = evaluateQuestions(
      {
        questions: [{ questionId: 'q1', stem: '题干' }],
        subject: '高中数学',
      },
      { signal: controller.signal, pollIntervalMs: 1 },
    )
    await vi.waitFor(() => expect(getTask).toHaveBeenCalled())

    controller.abort()

    await expect(promise).rejects.toMatchObject({ name: 'AbortError' })
  })
})
