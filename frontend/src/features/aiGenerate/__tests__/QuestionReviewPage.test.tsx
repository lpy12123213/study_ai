import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QuestionReviewPage from '@/features/aiGenerate/QuestionReviewPage'

const apiMocks = vi.hoisted(() => ({
  getQuestionLibrarySession: vi.fn(),
  reviewQuestionLibrarySessionQuestion: vi.fn(),
  approveQuestionLibrarySessionQuestion: vi.fn(),
  rejectQuestionLibrarySessionQuestion: vi.fn(),
  regenerateQuestionLibrarySection: vi.fn(),
}))

const clientMocks = vi.hoisted(() => ({
  downloadObjectUrl: vi.fn(),
  resolveApiResourceUrl: vi.fn((url: string) => `https://example.test${url.startsWith('/') ? url : `/${url}`}`),
}))

vi.mock('@/api/client', () => ({
  downloadObjectUrl: clientMocks.downloadObjectUrl,
  resolveApiResourceUrl: clientMocks.resolveApiResourceUrl,
}))

vi.mock('@/api/questionLibrary', async () => {
  const actual = await vi.importActual<typeof import('@/api/questionLibrary')>('@/api/questionLibrary')
  return {
    ...actual,
    getQuestionLibrarySession: apiMocks.getQuestionLibrarySession,
    reviewQuestionLibrarySessionQuestion: apiMocks.reviewQuestionLibrarySessionQuestion,
    approveQuestionLibrarySessionQuestion: apiMocks.approveQuestionLibrarySessionQuestion,
    rejectQuestionLibrarySessionQuestion: apiMocks.rejectQuestionLibrarySessionQuestion,
    regenerateQuestionLibrarySection: apiMocks.regenerateQuestionLibrarySection,
  }
})

vi.mock('@/stores/useNotificationStore', () => ({
  useNotificationStore: (selector: (state: { pushToast: ReturnType<typeof vi.fn> }) => unknown) =>
    selector({ pushToast: vi.fn() }),
}))

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/ai-generate/review/session-001/q-001']}>
        <Routes>
          <Route path="/ai-generate/review/:sessionId/:questionId" element={<QuestionReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('QuestionReviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    clientMocks.downloadObjectUrl.mockResolvedValue({
      objectUrl: 'blob:diagram-review',
      revoke: vi.fn(),
    })
    apiMocks.getQuestionLibrarySession.mockResolvedValue({
      success: true,
      session: {
        session_id: 'session-001',
        preview_id: 'preview-001',
        status: 'pending_review',
        mode: 'standard',
        subject: '高中物理',
        topic: '电磁感应',
        count: 1,
        task_ids: ['task-001'],
        latest_task_id: 'task-001',
        updated_at_s: 1710000000,
        created_at_s: 1710000000,
        reasoning_blocks_count: 0,
        confirmed_question_ids: [],
        stop_requested: false,
        draft_questions: [
          {
            question_id: 'q-001',
            stem: '在高中物理拓展实验课程中，你需要设计实验探究双轨模型中电感对导体棒运动的影响。',
            answer: '实验方案略。',
            analysis: '分析略。',
            keep: true,
            review_status: 'pending_review',
            review: null,
            diagrams: [
              {
                url: `/api/media/generated/${'b'.repeat(64)}.png`,
                alt: '双轨模型实验装置示意图',
                caption: '图1: 双轨模型实验装置图',
              },
            ],
          },
        ],
        reasoning_blocks: [],
        task_events: [],
      },
    })
  })

  it('renders draft diagrams and loads generated media through authenticated blob URLs', async () => {
    renderPage()

    expect(await screen.findByText('生成题单题审查页')).toBeInTheDocument()
    expect(await screen.findByText('配图')).toBeInTheDocument()
    expect(screen.getByText('图1: 双轨模型实验装置图')).toBeInTheDocument()

    const diagram = await screen.findByAltText('双轨模型实验装置示意图')
    await waitFor(() => expect(diagram).toHaveAttribute('src', 'blob:diagram-review'))
    expect(clientMocks.downloadObjectUrl).toHaveBeenCalledWith(`/api/media/generated/${'b'.repeat(64)}.png`)
  })
})
