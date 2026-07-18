import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StudyMaterialsWorkspace } from '@/features/generation/studyMaterials/components/StudyMaterialsWorkspace'
import type { StudyMaterialsController } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsController'

vi.mock('@/hooks/useVirtualMessages', () => ({
  useVirtualMessages: () => ({
    listRef: vi.fn(),
    totalHeight: 0,
    range: { start: 0, end: 0 },
    offsets: [],
    getMeasureRef: () => vi.fn(),
  }),
}))

vi.mock('@/components/task/TaskProgressHeader', () => ({
  TaskProgressHeader: () => <div>任务进度</div>,
}))

vi.mock('@/components/task/TaskTimeline', () => ({
  TaskTimeline: () => <div>任务时间线</div>,
}))

function makeController(overrides: Record<string, unknown> = {}) {
  return {
    scrollRef: { current: null },
    leftRatio: 0.68,
    showSplitPane: true,
    messages: [],
    handleMessageScroll: vi.fn(),
    isNearBottom: true,
    scrollToBottom: vi.fn(),
    hasResumableStream: false,
    isGenerating: true,
    activeConversationId: 'conversation-1',
    activeConversation: null,
    resumeActiveStream: vi.fn(),
    discardResumableStream: vi.fn(),
    isLastExportFailure: false,
    startContinueIteration: vi.fn(),
    lastTaskStatus: null,
    lastTaskStatusError: '',
    lastFailedStage: '',
    lastTaskResumable: true,
    error: null,
    clearError: vi.fn(),
    hasSubAgentPane: true,
    subAgentActivities: [
      {
        knowledgePoint: '函数单调性',
        status: 'running',
        steps: [],
      },
    ],
    activeSubAgentTab: '函数单调性',
    setActiveSubAgentTab: vi.fn(),
    setSubAgentCollapsed: vi.fn(),
    handleDrag: vi.fn(),
    ...overrides,
  } as unknown as StudyMaterialsController
}

const failedConversation = {
  id: 'conversation-1',
  title: '函数单调性',
  type: 'study_materials',
  createdAt: '2026-06-10T00:00:00.000Z',
  updatedAt: '2026-06-10T00:00:00.000Z',
  status: 'failed',
  resumable: false,
  lastTask: { taskType: 'study_materials', taskId: 'task-9', lastSeq: 3 },
}

describe('StudyMaterialsWorkspace', () => {
  afterEach(() => {
    cleanup()
  })

  it('renders the research pane as an Aurora sidecar while generating', () => {
    const { container } = render(<StudyMaterialsWorkspace controller={makeController()} />)

    const sidecar = container.querySelector('.aurora-materials-sidecar')

    expect(sidecar).toBeInTheDocument()
    expect(sidecar).toHaveAttribute('data-state', 'running')
  })

  it('does not leak Agent/SubAgent wording in the visible copy', () => {
    const { container } = render(<StudyMaterialsWorkspace controller={makeController()} />)

    expect(container.textContent).not.toMatch(/SubAgent|主 Agent|Main Agent/i)
    expect(screen.getByText('知识点研究区')).toBeInTheDocument()
  })

  it('offers fix/skip export continuations when the failed task is resumable at export stage', () => {
    const startContinueIteration = vi.fn()
    render(
      <StudyMaterialsWorkspace
        controller={makeController({
          isGenerating: false,
          activeConversation: failedConversation,
          lastTaskStatus: { last_failed_stage: 'export', resumable: true },
          lastFailedStage: 'export',
          lastTaskResumable: true,
          startContinueIteration,
        })}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: '修复导出' }))
    fireEvent.click(screen.getByRole('button', { name: '跳过导出' }))
    fireEvent.click(screen.getByRole('button', { name: '重新规划' }))

    expect(startContinueIteration).toHaveBeenNthCalledWith(1, 'fix_export')
    expect(startContinueIteration).toHaveBeenNthCalledWith(2, 'skip_export')
    expect(startContinueIteration).toHaveBeenNthCalledWith(3, 'replan_from_failure')
  })

  it('hides continuation actions when the backend reports the failed task as not resumable', () => {
    render(
      <StudyMaterialsWorkspace
        controller={makeController({
          isGenerating: false,
          activeConversation: failedConversation,
          lastTaskStatus: { last_failed_stage: '', resumable: false },
          lastTaskResumable: false,
        })}
      />
    )

    expect(screen.getByText(/本次失败没有可恢复的进度/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新规划' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '修复导出' })).not.toBeInTheDocument()
  })

  it.each([
    ['plan', '规划', '继续规划'],
    ['research', '检索研究', '继续研究'],
    ['draft', '起草', '继续起草'],
    ['review', '审查', '继续审查'],
    ['revise', '修订', '继续修订'],
    ['accept', '验收', '继续验收'],
  ])('continues the exact %s workflow failure from the UI', (stage, label, buttonLabel) => {
    const startContinueIteration = vi.fn()
    render(
      <StudyMaterialsWorkspace
        controller={makeController({
          isGenerating: false,
          activeConversation: failedConversation,
          lastFailedStage: stage,
          lastTaskResumable: true,
          startContinueIteration,
        })}
      />
    )

    expect(screen.getByText(new RegExp(`上次失败阶段：${label}`))).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: buttonLabel }))
    expect(startContinueIteration).toHaveBeenCalledWith('resume_failed_stage')
  })

  it('offers fix/skip export from the completed banner after an export failure', () => {
    const startContinueIteration = vi.fn()
    render(
      <StudyMaterialsWorkspace
        controller={makeController({
          isGenerating: false,
          activeConversation: {
            ...failedConversation,
            status: 'completed',
            lastTask: {
              taskType: 'study_materials',
              taskId: 'task-9',
              lastSeq: 9,
              materialError: { tool: 'compile_latex_to_pdf', error: 'boom' },
            },
          },
          isLastExportFailure: true,
          startContinueIteration,
        })}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: '修复导出' }))
    fireEvent.click(screen.getByRole('button', { name: '继续迭代优化' }))

    expect(startContinueIteration).toHaveBeenNthCalledWith(1, 'fix_export')
    expect(startContinueIteration).toHaveBeenNthCalledWith(2, 'improve')
  })
})
