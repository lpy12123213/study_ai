import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ExamPage from '@/pages/ExamPage'
import { useExamStore } from '@/stores/useExamStore'
import type { ExamSession } from '@/types/exam'

const apiMocks = vi.hoisted(() => ({
  batchSaveAnswers: vi.fn(),
  getExamSession: vi.fn(),
  getExamSessions: vi.fn(),
  getExamResult: vi.fn(),
  saveAnswer: vi.fn(),
  startExam: vi.fn(),
  submitExam: vi.fn(),
  uploadHandwriting: vi.fn(),
}))

const handwritingMocks = vi.hoisted(() => ({
  exportImage: vi.fn(),
  mountCount: 0,
}))

vi.mock('@/api/exam', () => apiMocks)

vi.mock('@/features/exam/components/HandwritingBoard', async () => {
  const React = await vi.importActual<typeof import('react')>('react')

  return {
    HandwritingBoard: React.forwardRef((props: any, ref: any) => {
      const [mountId] = React.useState(() => {
        handwritingMocks.mountCount += 1
        return handwritingMocks.mountCount
      })
      React.useImperativeHandle(
        ref,
        () => ({
          exportImage: async () => {
            handwritingMocks.exportImage()
            await props.onImageFile(new File(['handwriting'], 'handwriting.jpg', { type: 'image/jpeg' }))
          },
        }),
        [props]
      )
      return React.createElement('div', { 'data-testid': 'handwriting-board' }, `mock handwriting board ${mountId}`)
    }),
  }
})

function makeSession(overrides: Partial<ExamSession> = {}): ExamSession {
  return {
    sessionId: 'session-001',
    paperId: 7,
    paperName: '函数综合测试',
    mode: 'untimed',
    timeLimitMinutes: null,
    startedAt: '2026-06-05T10:00:00',
    submittedAt: null,
    expiresAt: null,
    status: 'in_progress',
    totalScore: 0,
    maxScore: 15,
    questions: [
      {
        questionId: 'q-001',
        order: 1,
        type: 'calculation',
        questionType: 'calculation',
        stem: '写出计算过程。',
        maxScore: 10,
      },
      {
        questionId: 'q-002',
        order: 2,
        type: 'single_choice',
        questionType: 'single_choice',
        stem: '选择正确答案。A. 1 B. 2 C. 3 D. 4',
        maxScore: 5,
      },
    ],
    ...overrides,
  }
}

function renderExamPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/exam/session-001']}>
        <Routes>
          <Route path="/exam/:sessionId" element={<ExamPage />} />
          <Route path="/exam/:sessionId/result" element={<div>result page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ExamPage', () => {
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    handwritingMocks.mountCount = 0
    useExamStore.getState().reset()
    apiMocks.getExamSession.mockResolvedValue(makeSession())
    apiMocks.batchSaveAnswers.mockResolvedValue([])
    apiMocks.uploadHandwriting.mockResolvedValue({
      path: 'user-1/session-001/q-001.jpg',
      url: '/api/media/exam-handwriting/session-001/q-001.jpg',
    })
  })

  it('loads the session with saved answers so interrupted exams can be restored', async () => {
    renderExamPage()

    expect(await screen.findByText('函数综合测试')).toBeInTheDocument()
    await waitFor(() =>
      expect(apiMocks.getExamSession).toHaveBeenCalledWith('session-001', { includeAnswers: true })
    )
  })

  it('exports and saves the current handwriting before moving to another question', async () => {
    const user = userEvent.setup()
    renderExamPage()

    expect(await screen.findByTestId('handwriting-board')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /下一题/ }))

    await waitFor(() => expect(handwritingMocks.exportImage).toHaveBeenCalledTimes(1))
    expect(apiMocks.uploadHandwriting).toHaveBeenCalledWith('session-001', 'q-001', expect.any(File))
    await waitFor(() =>
      expect(apiMocks.batchSaveAnswers).toHaveBeenCalledWith('session-001', [
        {
          questionId: 'q-001',
          questionType: 'calculation',
          handwritingImagePath: 'user-1/session-001/q-001.jpg',
        },
      ])
    )
  })

  it('does not recreate save intervals on answer edits or timer ticks', async () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval')
    apiMocks.getExamSession.mockResolvedValue(
      makeSession({
        mode: 'timed',
        expiresAt: '2026-06-05T10:30:00',
      })
    )
    renderExamPage()

    expect(await screen.findByText('函数综合测试')).toBeInTheDocument()
    await waitFor(() => expect(setIntervalSpy.mock.calls.some((call) => call[1] === 30_000)).toBe(true))
    const initialSaveIntervalCount = setIntervalSpy.mock.calls.filter((call) => call[1] === 30_000).length

    act(() => {
      useExamStore.getState().updateAnswer('q-002', {
        questionId: 'q-002',
        questionType: 'single_choice',
        selectedOptions: ['A'],
      })
      useExamStore.getState().tick('2026-06-05T10:30:00')
    })

    await Promise.resolve()
    expect(setIntervalSpy.mock.calls.filter((call) => call[1] === 30_000)).toHaveLength(initialSaveIntervalCount)
  })

  it('submits only once when a timed exam expires', async () => {
    const intervals: Array<{ handler: TimerHandler; delay?: number }> = []
    vi.spyOn(window, 'setInterval').mockImplementation((handler: TimerHandler, delay?: number) => {
      intervals.push({ handler, delay })
      return intervals.length as unknown as ReturnType<typeof window.setInterval>
    })
    vi.spyOn(window, 'clearInterval').mockImplementation(() => undefined)
    let resolveSubmit: (value: unknown) => void = () => undefined
    apiMocks.getExamSession.mockResolvedValue(
      makeSession({
        mode: 'timed',
        expiresAt: '2026-06-05T09:59:59',
      })
    )
    apiMocks.submitExam.mockReturnValue(new Promise((resolve) => {
      resolveSubmit = resolve
    }))
    renderExamPage()

    expect(await screen.findByText('函数综合测试')).toBeInTheDocument()
    const tick = intervals.find((item) => item.delay === 1000)?.handler
    expect(tick).toBeTypeOf('function')

    await act(async () => {
      if (typeof tick === 'function') {
        tick()
        tick()
      }
      await Promise.resolve()
    })

    expect(apiMocks.submitExam).toHaveBeenCalledTimes(1)
    resolveSubmit({ sessionId: 'session-001' })
  })

  it('remounts handwriting board when moving between handwriting questions', async () => {
    const user = userEvent.setup()
    apiMocks.getExamSession.mockResolvedValue(
      makeSession({
        questions: [
          {
            questionId: 'q-001',
            order: 1,
            type: 'calculation',
            questionType: 'calculation',
            stem: '第一道计算题。',
            maxScore: 10,
          },
          {
            questionId: 'q-002',
            order: 2,
            type: 'calculation',
            questionType: 'calculation',
            stem: '第二道计算题。',
            maxScore: 10,
          },
        ],
      })
    )
    renderExamPage()

    expect(await screen.findByText('mock handwriting board 1')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /下一题/ }))

    expect(await screen.findByText('mock handwriting board 2')).toBeInTheDocument()
  })

  it('renders exam stems with question formula tokens', async () => {
    apiMocks.getExamSession.mockResolvedValue(
      makeSession({
        questions: [
          {
            questionId: 'q-formula',
            order: 1,
            type: 'single_choice',
            questionType: 'single_choice',
            stem: `已知 \\(x^2+1\\)，并参考[公式:${'a'.repeat(32)}]。A. 1 B. 2`,
            maxScore: 5,
          },
        ],
      })
    )
    renderExamPage()

    expect(await screen.findByAltText('题目公式')).toBeInTheDocument()
    await waitFor(() => expect(document.querySelector('.katex')).not.toBeNull())
  })
})
