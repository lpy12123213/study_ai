import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ReviewSession } from '@/features/wrongbook/components/ReviewSession'
import * as wrongbookApi from '@/api/wrongbook'

vi.mock('@/api/wrongbook', () => ({
  getReviewQueue: vi.fn(),
  recordReview: vi.fn(),
}))

function renderReviewSession() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ReviewSession />
    </QueryClientProvider>,
  )
}

describe('ReviewSession', () => {
  beforeEach(() => {
    vi.mocked(wrongbookApi.getReviewQueue)
      .mockResolvedValueOnce({
        due_count: 1,
        total: 1,
        items: [
          {
            id: 1,
            question_id: 'q-review',
            subject: '高中数学',
            knowledge_point: '函数',
            mastery: 30,
            note: '顶点式不熟',
            tags: [],
            source_ref: {},
            question: {
              stem: '设 f(x)=x^2，求顶点。',
              answer: '(0,0)',
              analysis: '二次函数标准形式。',
            },
          },
        ],
      })
      .mockResolvedValue({
        due_count: 0,
        total: 0,
        items: [],
      })
    vi.mocked(wrongbookApi.recordReview).mockResolvedValue({
      id: 1,
      question_id: 'q-review',
      subject: '高中数学',
      knowledge_point: '函数',
      mastery: 45,
      note: '顶点式不熟',
      tags: [],
      source_ref: {},
      interval_days: 1,
      repetitions: 1,
      next_review_at: '2026-01-02T09:00:00',
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('reveals the answer and records a review rating before showing the completion state', async () => {
    const user = userEvent.setup()
    renderReviewSession()

    expect(await screen.findByText('q-review')).toBeInTheDocument()
    expect(screen.getByText('设 f(x)=x^2，求顶点。')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '显示答案' }))
    expect(screen.getByText('(0,0)')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '记得' }))

    await waitFor(() => expect(wrongbookApi.recordReview).toHaveBeenCalledWith('q-review', 'good'))
    expect(await screen.findByText('本轮复习已完成')).toBeInTheDocument()
  })
})
