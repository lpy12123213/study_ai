import { render, screen } from '@testing-library/react'
import { act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BlueprintPage from '@/pages/BlueprintPage'

const apiMocks = vi.hoisted(() => ({
  generateFullPaperStream: vi.fn(),
}))

const formDraftMocks = vi.hoisted(() => ({
  restored: null as any,
  clearDraft: vi.fn(),
}))

vi.mock('@/api/papers', async () => {
  const actual = await vi.importActual<typeof import('@/api/papers')>('@/api/papers')
  return {
    ...actual,
    generateFullPaperStream: apiMocks.generateFullPaperStream,
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
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

vi.mock('@/hooks/useBlueprint', () => ({
  useComposePaper: () => ({
    compose: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    isComposing: false,
    result: null,
    taskId: null,
    progress: 0,
  }),
  useSaveBlueprint: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}))

vi.mock('@/hooks/useFormDraft', () => ({
  useFormDraft: (options: any) => {
    if (formDraftMocks.restored) {
      options?.onRestore?.(formDraftMocks.restored)
    }
    return { clearDraft: formDraftMocks.clearDraft }
  },
}))

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector: any) => selector({ user: { id: '1' } }),
}))

vi.mock('@/stores/useTaskStore', () => ({
  useTaskStore: (selector: any) =>
    selector({
      getTaskSteps: () => [],
      getCheckpoint: () => undefined,
    }),
}))

vi.mock('@/api/tasks', () => ({
  getTask: vi.fn(),
}))

vi.mock('@/components/task/TaskProgressHeader', () => ({
  TaskProgressHeader: ({ taskId }: { taskId?: string }) => <div>{`task-progress:${taskId || 'none'}`}</div>,
}))

vi.mock('@/components/task/TaskTimeline', () => ({
  TaskTimeline: ({ steps }: { steps: Array<{ title: string }> }) => (
    <div>{steps.map((step) => step.title).join(' | ') || 'timeline-empty'}</div>
  ),
}))

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/blueprint']}>
      <BlueprintPage />
    </MemoryRouter>
  )
}

describe('BlueprintPage (one-click mode)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    formDraftMocks.restored = null
  })

  it('switches modes via tabs', async () => {
    renderPage()

    expect(screen.getByRole('tab', { name: '蓝图组卷' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '一键组卷' })).toBeInTheDocument()

    // Default is blueprint mode
    expect(screen.getByText('题型配置')).toBeInTheDocument()

    await act(async () => {
      screen.getByRole('tab', { name: '一键组卷' }).click()
    })
    expect(screen.getByText('一键组卷参数')).toBeInTheDocument()
  })

  it('starts generate-full stream and renders result', async () => {
    formDraftMocks.restored = {
      mode: 'one_click',
      subject: '高中数学',
      topic: '导数',
      blueprintName: '导数综合卷',
      oneClickTotalPoints: 150,
      oneClickTimeLimit: 120,
      oneClickHardPct: 20,
      oneClickUseArchive: true,
      slots: [],
    }

    renderPage()

    expect(screen.getByText('一键组卷参数')).toBeInTheDocument()

    await act(async () => {
      screen.getByRole('button', { name: '一键生成' }).click()
    })

    expect(apiMocks.generateFullPaperStream).toHaveBeenCalledTimes(1)

    const [_req, onEvent] = apiMocks.generateFullPaperStream.mock.calls[0]
    expect(_req).toMatchObject({
      subject: '高中数学',
      topic: '导数',
      paperName: '导数综合卷',
      totalPoints: 150,
      timeLimit: 120,
    })

    await act(async () => {
      onEvent({
        type: 'result',
        result: { paper_id: 12, paper_name: '导数综合卷', question_count: 20 },
      })
    })

    expect(await screen.findByText('一键组卷完成')).toBeInTheDocument()
    expect(screen.getByText('已生成试卷，包含 20 道题目')).toBeInTheDocument()
  })
})

