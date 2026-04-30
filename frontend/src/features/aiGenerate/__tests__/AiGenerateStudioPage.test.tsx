import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AiGenerateStudioPage } from '@/features/aiGenerate/AiGenerateStudioPage'

const apiMocks = vi.hoisted(() => ({
  listQuestionLibrarySessions: vi.fn(),
  getQuestionLibrarySession: vi.fn(),
}))

vi.mock('@/api/questionLibrary', async () => {
  const actual = await vi.importActual<typeof import('@/api/questionLibrary')>('@/api/questionLibrary')
  return {
    ...actual,
    listQuestionLibrarySessions: apiMocks.listQuestionLibrarySessions,
    getQuestionLibrarySession: apiMocks.getQuestionLibrarySession,
    commitQuestionLibraryPreview: vi.fn(),
    discardQuestionLibraryPreview: vi.fn(),
    regenerateQuestionLibrarySection: vi.fn(),
    stopQuestionLibrarySession: vi.fn(),
    archiveQuestionLibrarySession: vi.fn(),
    confirmQuestionLibrarySessionQuestion: vi.fn(),
    unconfirmQuestionLibrarySessionQuestion: vi.fn(),
  }
})

vi.mock('@/hooks/useSubjects', () => ({
  useSubjects: () => ({
    data: [{ id: 1, code: '高中数学', name: '高中数学' }],
  }),
  useSubjectFilters: () => ({
    data: {
      grades: [{ id: 1, name: '高一' }],
      textbookVersions: [{ id: 'tj-rjb-a', name: '人教A版' }],
    },
  }),
  useSubjectKnowledgeTree: () => ({
    data: {
      nodes: [
        {
          id: 'chapter-1',
          label: '函数',
          type: 'chapter',
          children: [{ id: 'kp-1', label: '函数单调性', type: 'knowledge_point', selectable: true }],
        },
      ],
    },
    isFetching: false,
    error: null,
  }),
}))

vi.mock('@/features/questionLibrary/hooks/useQuestionLibrary', () => ({
  useQuestionLibrary: () => ({
    filters: { subject: '高中数学' },
    total: 12,
    setSubject: vi.fn(),
    refreshList: vi.fn(),
    refreshDetail: vi.fn(),
    detail: null,
  }),
}))

vi.mock('@/features/questionLibrary/hooks/useQuestionLibraryTasks', () => ({
  useQuestionLibraryTasks: () => ({
    preferredTask: null,
    draftPreview: null,
    runGenerate: vi.fn(() => 'task-001'),
    clearDraftPreview: vi.fn(),
    getTaskEvents: vi.fn(() => []),
  }),
}))

vi.mock('@/stores/useNotificationStore', () => ({
  useNotificationStore: (selector: (state: { pushToast: ReturnType<typeof vi.fn> }) => unknown) =>
    selector({ pushToast: vi.fn() }),
}))

vi.mock('@/components/task/TaskProgressHeader', () => ({
  TaskProgressHeader: ({ taskId }: { taskId?: string }) => <div>{`task-progress:${taskId || 'none'}`}</div>,
}))

vi.mock('@/components/task/TaskTimeline', () => ({
  TaskTimeline: ({ steps }: { steps: Array<{ title: string }> }) => (
    <div>{steps.map((step) => step.title).join(' | ') || 'timeline-empty'}</div>
  ),
}))

function createSessionSummary(overrides: Record<string, unknown> = {}) {
  return {
    session_id: 'session-001',
    preview_id: 'preview-001',
    status: 'pending_review',
    mode: 'infinite',
    subject: '高中数学',
    topic: '函数单调性',
    count: 1,
    task_ids: ['task-001'],
    latest_task_id: 'task-001',
    updated_at_s: 1710000000,
    created_at_s: 1710000000,
    reasoning_blocks_count: 0,
    confirmed_question_ids: [],
    stop_requested: true,
    ...overrides,
  }
}

function createSessionDetail(overrides: Record<string, unknown> = {}) {
  return {
    session_id: 'session-001',
    preview_id: 'preview-001',
    status: 'pending_review',
    mode: 'infinite',
    subject: '高中数学',
    topic: '函数单调性',
    count: 1,
    task_ids: ['task-001'],
    latest_task_id: 'task-001',
    updated_at_s: 1710000000,
    created_at_s: 1710000000,
    reasoning_blocks_count: 0,
    confirmed_question_ids: [],
    stop_requested: true,
    difficulty: '中等',
    question_type: '解答题',
    use_study_archive: true,
    grade_id: '1',
    textbook_version_id: 'tj-rjb-a',
    knowledge_point_ids: ['kp-1'],
    knowledge_points: ['函数单调性'],
    stream_reasoning: true,
    draft_questions: [],
    reasoning_blocks: [],
    task_events: [],
    ...overrides,
  }
}

function renderPage(initialEntry = '/ai-generate?session=session-001') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <AiGenerateStudioPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AiGenerateStudioPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listQuestionLibrarySessions.mockReset()
    apiMocks.getQuestionLibrarySession.mockReset()
    vi.useRealTimers()
  })

  it('renders a simplified workspace and shows generated questions in a floating window', async () => {
    apiMocks.listQuestionLibrarySessions.mockResolvedValue({
      success: true,
      sessions: [
        createSessionSummary({
          reasoning_blocks_count: 2,
        }),
      ],
    })

    apiMocks.getQuestionLibrarySession.mockResolvedValue({
      success: true,
      session: createSessionDetail({
        reasoning_blocks_count: 2,
        draft_questions: [
          {
            question_id: 'q-001',
            stem: '已知函数 f(x)，判断其单调区间。',
            answer: '在区间 (0,+∞) 单调递增。',
            analysis: '先求导。',
            keep: true,
            review_status: 'pending_review',
            review: null,
          },
        ],
        reasoning_blocks: [
          {
            id: 'reason-1',
            task_id: 'task-001',
            stage_id: 'draft_realization',
            stage_label: '草稿生成',
            source: 'raw',
            content: '先确认题量和难度约束。',
            created_at: '2026-03-20T10:00:00Z',
          },
        ],
        task_events: [
          {
            taskId: 'task-001',
            seq: 8,
            type: 'reasoning_status',
            data: {
              stage_id: 'judge',
              stage_label: '判题筛选',
              mode: 'trace',
              message: '当前模型未返回原始 reasoning，已降级为事件级 trace。',
            },
            created_at: '2026-03-20T10:00:01Z',
          },
        ],
      }),
    })

    renderPage()

    expect(await screen.findByText('AI 出题')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '会话历史' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '知识点配置' })).toBeInTheDocument()

    const floatingWindow = await screen.findByRole('complementary', { name: '题目悬浮窗' })
    expect(floatingWindow).toBeInTheDocument()
    expect(within(floatingWindow).getByText('已知函数 f(x)，判断其单调区间。')).toBeInTheDocument()
    expect(await screen.findByText('原始 Reason')).toBeInTheDocument()
    expect(await screen.findByText('事件 Trace')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '停止追加' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: '进入审查' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '审核通过并入库' })).toBeEnabled()
  })

  it('can collapse the floating question window and reopen it from the floating trigger', async () => {
    apiMocks.listQuestionLibrarySessions.mockResolvedValue({
      success: true,
      sessions: [createSessionSummary()],
    })

    apiMocks.getQuestionLibrarySession.mockResolvedValue({
      success: true,
      session: createSessionDetail({
        draft_questions: [
          {
            question_id: 'q-001',
            stem: '已知函数 f(x)，判断其单调区间。',
            answer: '在区间 (0,+∞) 单调递增。',
            analysis: '先求导。',
            keep: true,
            review_status: 'pending_review',
            review: null,
          },
        ],
      }),
    })

    renderPage()

    expect(await screen.findByRole('complementary', { name: '题目悬浮窗' })).toBeInTheDocument()
    screen.getByRole('button', { name: '收起题目悬浮窗' }).click()

    expect(screen.queryByRole('complementary', { name: '题目悬浮窗' })).not.toBeInTheDocument()
    expect(screen.queryByText('已知函数 f(x)，判断其单调区间。')).not.toBeInTheDocument()

    const openButtons = screen.getAllByRole('button', { name: '打开题目悬浮窗' })
    openButtons[openButtons.length - 1].click()
    expect(await screen.findByText('已知函数 f(x)，判断其单调区间。')).toBeInTheDocument()
  })

  it('polls running sessions and restores drafts after refresh', async () => {
    vi.useFakeTimers()
    try {
      apiMocks.listQuestionLibrarySessions.mockResolvedValue({
        success: true,
        sessions: [
          createSessionSummary({
            session_id: 'session-running-1',
            preview_id: 'preview-running-1',
            status: 'running',
            mode: 'standard',
            topic: '导数',
            count: 1,
            task_ids: ['task-running-1'],
            latest_task_id: 'task-running-1',
            updated_at_s: 1710000100,
            reasoning_blocks_count: 0,
            stop_requested: false,
          }),
        ],
      })

      apiMocks.getQuestionLibrarySession
        .mockResolvedValueOnce({
          success: true,
          session: createSessionDetail({
            session_id: 'session-running-1',
            preview_id: 'preview-running-1',
            status: 'running',
            mode: 'standard',
            topic: '导数',
            count: 1,
            task_ids: ['task-running-1'],
            latest_task_id: 'task-running-1',
            updated_at_s: 1710000100,
            stop_requested: false,
            use_study_archive: false,
            draft_questions: [],
            reasoning_blocks: [],
            task_events: [],
          }),
        })
        .mockResolvedValueOnce({
          success: true,
          session: createSessionDetail({
            session_id: 'session-running-1',
            preview_id: 'preview-running-1',
            status: 'running',
            mode: 'standard',
            topic: '导数',
            count: 1,
            task_ids: ['task-running-1'],
            latest_task_id: 'task-running-1',
            updated_at_s: 1710000200,
            stop_requested: false,
            use_study_archive: false,
            draft_questions: [
              {
                question_id: 'q-running-1',
                stem: '轮询恢复题干',
                answer: '轮询恢复答案',
                analysis: '轮询恢复解析',
                keep: true,
                review_status: 'pending_review',
                review: null,
              },
            ],
            reasoning_blocks: [],
            task_events: [],
          }),
        })

      renderPage('/ai-generate?session=session-running-1')

      await act(async () => {
        await Promise.resolve()
      })

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000)
        await Promise.resolve()
      })

      expect(apiMocks.getQuestionLibrarySession).toHaveBeenCalledTimes(2)
      expect(screen.getByRole('button', { name: '生成中' })).toBeDisabled()
      expect(screen.getAllByText('轮询恢复题干').length).toBeGreaterThan(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps infinite continue-generation optimistic state while stale stop_requested is still polling back', async () => {
    vi.useFakeTimers()
    try {
      apiMocks.listQuestionLibrarySessions.mockResolvedValue({
        success: true,
        sessions: [
          createSessionSummary({
            session_id: 'session-race-1',
            preview_id: 'preview-race-1',
            status: 'stopped',
            topic: '导数',
            task_ids: ['task-race-0'],
            latest_task_id: 'task-race-0',
            updated_at_s: 1710000500,
            reasoning_blocks_count: 0,
          }),
        ],
      })

      apiMocks.getQuestionLibrarySession.mockResolvedValue({
        success: true,
        session: createSessionDetail({
          session_id: 'session-race-1',
          preview_id: 'preview-race-1',
          status: 'stopped',
          topic: '导数',
          task_ids: ['task-race-0'],
          latest_task_id: 'task-race-0',
          updated_at_s: 1710000500,
          reasoning_blocks_count: 0,
          use_study_archive: false,
          knowledge_point_ids: [],
          knowledge_points: [],
          draft_questions: [],
          reasoning_blocks: [],
          task_events: [],
        }),
      })

      renderPage('/ai-generate?session=session-race-1')

      await act(async () => {
        await Promise.resolve()
      })

      expect(screen.getByRole('button', { name: '继续生成' })).toBeEnabled()
      screen.getByRole('button', { name: '继续生成' }).click()

      expect(screen.getAllByRole('button', { name: '生成中' }).some((button) => (button as HTMLButtonElement).disabled)).toBe(true)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000)
        await Promise.resolve()
      })

      expect(screen.getAllByRole('button', { name: '生成中' }).some((button) => (button as HTMLButtonElement).disabled)).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  }, 15000)

  it('renders partial failure sessions with a localized status label', async () => {
    apiMocks.listQuestionLibrarySessions.mockResolvedValue({
      success: true,
      sessions: [
        createSessionSummary({
          session_id: 'session-partial-1',
          preview_id: 'preview-partial-1',
          status: 'partial_failure',
          mode: 'standard',
          topic: '导数',
          task_ids: ['task-partial-1'],
          latest_task_id: 'task-partial-1',
          updated_at_s: 1710000300,
          reasoning_blocks_count: 0,
          stop_requested: false,
        }),
      ],
    })

    apiMocks.getQuestionLibrarySession.mockResolvedValue({
      success: true,
      session: createSessionDetail({
        session_id: 'session-partial-1',
        preview_id: 'preview-partial-1',
        status: 'partial_failure',
        mode: 'standard',
        topic: '导数',
        task_ids: ['task-partial-1'],
        latest_task_id: 'task-partial-1',
        updated_at_s: 1710000300,
        reasoning_blocks_count: 0,
        stop_requested: false,
        use_study_archive: false,
        knowledge_point_ids: [],
        knowledge_points: [],
        draft_questions: [],
        reasoning_blocks: [],
        task_events: [],
      }),
    })

    renderPage('/ai-generate?session=session-partial-1')

    expect((await screen.findAllByText('部分完成')).length).toBeGreaterThan(0)
  })
})
