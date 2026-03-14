import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AiGenerateStudioPage } from '@/pages/aiGenerate/AiGenerateStudioPage'

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
    preferredTask: null,
    draftPreview: null,
    runGenerate: vi.fn(() => 'task-001'),
    clearDraftPreview: vi.fn(),
  }),
}))

describe('AiGenerateStudioPage', () => {
  it('renders the studio shell header and primary action', () => {
    render(<AiGenerateStudioPage />)

    expect(screen.getByText('AI 出题工作台')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始生成' })).toBeInTheDocument()
    expect(screen.getByText('本次任务')).toBeInTheDocument()
  })
})
