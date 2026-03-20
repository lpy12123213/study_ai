import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AiGenerateStudioPage } from '@/pages/aiGenerate/AiGenerateStudioPage'

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

vi.mock('@/pages/questionLibrary/hooks/useQuestionLibrary', () => ({
  useQuestionLibrary: () => ({
    filters: { subject: '高中数学' },
    total: 12,
    setSubject: vi.fn(),
    refreshList: vi.fn(),
    refreshDetail: vi.fn(),
    detail: null,
  }),
}))

vi.mock('@/pages/questionLibrary/hooks/useQuestionLibraryTasks', () => ({
  useQuestionLibraryTasks: () => ({
    preferredTask: null,
    draftPreview: null,
    runGenerate: vi.fn(() => 'task-001'),
    clearDraftPreview: vi.fn(),
    getTaskEvents: vi.fn(() => []),
  }),
}))

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (state: { pushToast: ReturnType<typeof vi.fn> }) => unknown) =>
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
  it('renders session history, restored reasoning labels, and review-gated drafts', async () => {
    apiMocks.listQuestionLibrarySessions.mockResolvedValue({
      success: true,
      sessions: [
        {
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
          reasoning_blocks_count: 2,
          confirmed_question_ids: [],
          stop_requested: true,
        },
      ],
    })

    apiMocks.getQuestionLibrarySession.mockResolvedValue({
      success: true,
      session: {
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
        reasoning_blocks_count: 2,
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
      },
    })

    renderPage()

    expect(await screen.findByText('会话历史')).toBeInTheDocument()
    expect(await screen.findByText('函数单调性')).toBeInTheDocument()
    expect(await screen.findByText('原始 Reason')).toBeInTheDocument()
    expect(await screen.findByText('事件 Trace')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '停止追加' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: '进入审查' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认入库' })).toBeDisabled()
  })
})
