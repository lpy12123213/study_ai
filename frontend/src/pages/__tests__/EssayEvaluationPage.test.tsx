import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EssayEvaluationPage from '@/pages/EssayEvaluationPage'
import * as essayApi from '@/api/essayEvaluations'
import { useNotificationStore } from '@/stores/useNotificationStore'

vi.mock('@/api/essayEvaluations', () => ({
  evaluateEssay: vi.fn(),
  getEssayEvaluation: vi.fn(),
  listEssayEvaluations: vi.fn(),
}))

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <EssayEvaluationPage />
    </QueryClientProvider>,
  )
}

describe('EssayEvaluationPage', () => {
  beforeEach(() => {
    useNotificationStore.setState({ notifications: [], toasts: [] })
    vi.mocked(essayApi.listEssayEvaluations).mockResolvedValue({
      count: 1,
      items: [
        {
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
          summary: '列表摘要',
          strengths: [],
          weaknesses: [],
          suggestions: [],
          paragraph_feedback: [],
          rewrite: '',
          model: 'mock',
          created_at: '2026-06-08T10:00:00+08:00',
          updated_at: '2026-06-08T10:00:00+08:00',
        },
      ],
    })
    vi.mocked(essayApi.getEssayEvaluation).mockResolvedValue({
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
      summary: '历史详情已恢复',
      strengths: ['论点清晰'],
      weaknesses: [],
      suggestions: ['补充例子'],
      paragraph_feedback: [{ index: 0, excerpt: '第一段', issues: ['论据略少'], suggestion: '加入事例' }],
      rewrite: '',
      model: 'mock',
      created_at: '2026-06-08T10:00:00+08:00',
      updated_at: '2026-06-08T10:00:00+08:00',
      essay_text: '第一段。\n\n第二段。',
      requirements: '',
    })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    useNotificationStore.setState({ notifications: [], toasts: [] })
  })

  it('loads full evaluation details when a history item is selected', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: /成长/ }))

    await waitFor(() => expect(essayApi.getEssayEvaluation).toHaveBeenCalledWith(7))
    expect(await screen.findByText('历史详情已恢复')).toBeInTheDocument()
    expect(screen.getByText('论据略少')).toBeInTheDocument()
    expect(screen.getByText('第一段。')).toBeInTheDocument()
  })
})
