import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TaskCenterPage from '@/pages/TaskCenterPage'

const taskApiMocks = vi.hoisted(() => ({
  cancelTask: vi.fn(),
  getTask: vi.fn(),
  listTasks: vi.fn(),
  pauseTask: vi.fn(),
  resumeTask: vi.fn(),
  retryTask: vi.fn(),
  reviewComposedPaperTask: vi.fn(),
  streamTask: vi.fn(),
}))

vi.mock('@/api/tasks', () => ({
  cancelTask: taskApiMocks.cancelTask,
  getTask: taskApiMocks.getTask,
  listTasks: taskApiMocks.listTasks,
  pauseTask: taskApiMocks.pauseTask,
  resumeTask: taskApiMocks.resumeTask,
  retryTask: taskApiMocks.retryTask,
  reviewComposedPaperTask: taskApiMocks.reviewComposedPaperTask,
  streamTask: taskApiMocks.streamTask,
}))

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: (options: { count: number }) => ({
    getTotalSize: () => Number(options.count || 0) * 92,
    getVirtualItems: () =>
      Array.from({ length: Number(options.count || 0) }, (_, index) => ({
        index,
        key: String(index),
        start: index * 92,
      })),
    measureElement: vi.fn(),
  }),
}))

vi.mock('@/components/ui/scroll-area', () => ({
  ScrollArea: ({ children, className }: { children: ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}))

vi.mock('@/components/task/TaskTimeline', () => ({
  TaskTimeline: ({ steps }: { steps: Array<{ title: string }> }) => (
    <div data-testid="task-timeline">{steps.map((step) => step.title).join(' | ') || 'timeline-empty'}</div>
  ),
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
      <MemoryRouter initialEntries={['/tasks?status=running']}>
        <TaskCenterPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('TaskCenterPage', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('submits pending paper compose drafts from the review queue', async () => {
    const pendingTask = {
      id: 'task-review-1',
      task_type: 'paper_compose',
      title: '混合来源组卷',
      status: 'pending_review',
      progress: 90,
      last_seq: 3,
      created_at: '2026-06-08T10:00:00',
      updated_at: '2026-06-08T10:05:00',
      events: [
        {
          taskId: 'task-review-1',
          seq: 3,
          type: 'pending_review',
          data: {
            composeDraft: {
              paperName: '混合来源组卷',
              reviewSummary: { overall_score: 82 },
              questions: [
                {
                  question_id: 'q-review-1',
                  stem: '待人工审核题干',
                  type: '解答题',
                  difficulty: '困难',
                },
              ],
            },
          },
        },
      ],
    }
    const completedTask = {
      ...pendingTask,
      status: 'completed',
      progress: 100,
      last_seq: 5,
      result: {
        id: 88,
        name: '审核后保存试卷',
        questions: [{ questionId: 'q-review-2', stem: '保留题干' }],
      },
      events: [
        ...pendingTask.events,
        {
          taskId: 'task-review-1',
          seq: 4,
          type: 'step',
          data: {
            step: {
              id: 'compose_review',
              title: '人工审核完成',
              status: 'completed',
              toolName: 'compose-review',
              output: { paperId: 88, approved: 1, rejected: 1 },
            },
          },
        },
        {
          taskId: 'task-review-1',
          seq: 5,
          type: 'result',
          data: { result: { id: 88, name: '审核后保存试卷' } },
        },
      ],
    }
    taskApiMocks.listTasks.mockImplementation((params?: { status?: string }) =>
      Promise.resolve({
        count: params?.status === 'pending_review' ? 1 : 0,
        tasks: params?.status === 'pending_review' ? [pendingTask] : [],
      })
    )
    taskApiMocks.getTask.mockResolvedValueOnce(pendingTask).mockResolvedValue(completedTask)
    taskApiMocks.reviewComposedPaperTask.mockResolvedValue({
      success: true,
      paper: { paper_id: 88, paperId: 88, title: '混合来源组卷' },
    })

    const user = userEvent.setup()
    renderPage()

    await user.selectOptions(screen.getAllByRole('combobox')[0], 'pending_review')
    expect(await screen.findByText('混合来源组卷')).toBeInTheDocument()

    await user.click(screen.getByText('混合来源组卷'))
    expect(await screen.findByText('待人工审核题干')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /剔除 q-review-1/ }))
    await user.click(await screen.findByRole('button', { name: /提交人工审核/ }))

    await waitFor(() => {
      expect(taskApiMocks.reviewComposedPaperTask).toHaveBeenCalledWith('task-review-1', {
        questions: [{ questionId: 'q-review-1', status: 'rejected' }],
      })
    })
    expect(await screen.findByText('审核后保存试卷')).toBeInTheDocument()
    expect(screen.getAllByText('已完成').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: /提交人工审核/ })).not.toBeInTheDocument()
  })

  it('keeps the TaskCenter controls in responsive Aurora regions', async () => {
    taskApiMocks.listTasks.mockResolvedValue({ count: 0, tasks: [] })

    renderPage()

    expect(await screen.findByText('暂无任务')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /刷新/ }).closest('.aurora-task-actions')).toBeTruthy()
    expect(screen.getByText('暂无任务').closest('.aurora-task-body')).toBeTruthy()
  })
})
