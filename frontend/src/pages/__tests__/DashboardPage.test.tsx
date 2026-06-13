import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardPage from '@/pages/DashboardPage'
import WrongbookPage from '@/pages/WrongbookPage'

const dashboardApiMocks = vi.hoisted(() => ({
  getDashboardStats: vi.fn(),
}))

const insightsApiMocks = vi.hoisted(() => ({
  getInsightsOverview: vi.fn(),
}))

const wrongbookApiMocks = vi.hoisted(() => ({
  getReviewQueue: vi.fn(),
}))

vi.mock('@/api/dashboard', () => dashboardApiMocks)
vi.mock('@/api/insights', () => insightsApiMocks)
vi.mock('@/api/wrongbook', () => ({
  getReviewQueue: wrongbookApiMocks.getReviewQueue,
}))
vi.mock('@/api/client', () => ({
  downloadObjectUrl: vi.fn(),
}))
vi.mock('@/hooks/useRunningTasks', () => ({
  DASHBOARD_REFETCH_INTERVAL_MS: false,
  useRunningTasks: () => ({ data: { tasks: [] } }),
}))
vi.mock('@/features/wrongbook/components/WrongbookListPanel', () => ({
  WrongbookListPanel: () => <div>错题列表面板</div>,
}))
vi.mock('@/features/wrongbook/components/ReviewSession', () => ({
  ReviewSession: () => <div>复习会话</div>,
}))
vi.mock('@/features/wrongbook/components/MasteryPanel', () => ({
  MasteryPanel: () => <div>掌握度面板</div>,
}))

function renderWithQuery(children: ReactNode, initialEntry = '/') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DashboardPage', () => {
  beforeEach(() => {
    dashboardApiMocks.getDashboardStats.mockResolvedValue({
      from: '2026-06-01',
      to: '2026-06-08',
      tasks_total: 0,
      tasks_by_type: {},
      tasks_by_status: {},
      completion_rate: 0,
      avg_duration_s: 0,
      exports_total: 0,
      exports_by_type: {},
      top_subjects: [],
    })
    insightsApiMocks.getInsightsOverview.mockResolvedValue({
      from: '2026-06-01',
      to: '2026-06-08',
      subject: '',
      exams: {
        total_sessions: 0,
        avg_score_ratio: 0,
        trend: [],
        objective: { correct: 0, total: 0, ratio: 0 },
        subjective: { score: 0, max_score: 0, ratio: 0 },
        accuracy_by_type: [],
        recent: [],
      },
      essays: { total: 0, avg_score_ratio: 0, trend: [], by_type: [] },
      wrongbook: { total: 0, mastery_distribution: [], weak_points: [] },
      activity: {
        active_days: 0,
        current_streak: 0,
        plan_completion: { completed: 0, total: 0, overdue: 0, ratio: 0 },
      },
    })
    wrongbookApiMocks.getReviewQueue.mockResolvedValue({
      items: [],
      due_count: 7,
      total: 7,
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('links today review count to the wrongbook review tab', async () => {
    renderWithQuery(<DashboardPage />)

    const reviewText = await screen.findByText('今日待复习')
    const reviewLink = reviewText.closest('a')

    await waitFor(() => expect(within(reviewLink as HTMLElement).getByText('7')).toBeInTheDocument())
    expect(reviewLink).toHaveAttribute('href', '/wrongbook?tab=review')
    expect(wrongbookApiMocks.getReviewQueue).toHaveBeenCalledWith({ limit: 1 })
  })
})

describe('WrongbookPage', () => {
  beforeEach(() => {
    wrongbookApiMocks.getReviewQueue.mockResolvedValue({
      items: [],
      due_count: 3,
      total: 3,
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('opens the review tab from the dashboard link query', async () => {
    renderWithQuery(<WrongbookPage />, '/wrongbook?tab=review')

    const reviewTab = await screen.findByRole('tab', { name: /今日复习/ })

    expect(reviewTab).toHaveAttribute('aria-selected', 'true')
  })
})
