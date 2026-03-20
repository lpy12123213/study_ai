import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AiGenerateStudioPage } from '@/pages/aiGenerate/AiGenerateStudioPage'

let mockPreferredTask: any = null
let mockDraftPreview: any = null

vi.mock('@/hooks/useSubjects', () => ({
  useSubjects: () => ({
    data: [{ id: 1, code: '高中数学', name: '高中数学' }],
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
    preferredTask: mockPreferredTask,
    draftPreview: mockDraftPreview,
    runGenerate: vi.fn(() => 'task-001'),
    clearDraftPreview: vi.fn(),
  }),
}))

describe('AiGenerateStudioPage', () => {
  it('renders the studio shell header and primary action', () => {
    mockPreferredTask = null
    mockDraftPreview = null
    render(<AiGenerateStudioPage />)

    expect(screen.getByText('AI 出题工作台')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始生成' })).toBeInTheDocument()
    expect(screen.getByText('本次任务')).toBeInTheDocument()
  })

  it('shows task error details when generation fails', () => {
    mockDraftPreview = null
    mockPreferredTask = {
      taskId: 'task-err-1',
      status: 'failed',
      progress: 12,
      stage: '规格搜索',
      error: 'no_questions_generated',
    }

    render(<AiGenerateStudioPage />)

    expect(screen.getAllByText('no_questions_generated').length).toBeGreaterThan(0)
  })
})
