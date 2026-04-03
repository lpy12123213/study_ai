import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { QuestionDraftCard } from '@/pages/aiGenerate/QuestionDraftCard'
import type { AiGenerateDraftCard } from '@/pages/aiGenerate/types'

describe('QuestionDraftCard', () => {
  it('renders all artifact sections and exposes direct review-and-commit from the draft stream', () => {
    const draft: AiGenerateDraftCard = {
      id: 'draft-card-1',
      questionId: 'q-001',
      title: '题目 01',
      index: 0,
      keep: true,
      status: 'ready',
      reviewStatus: 'pending_review',
      review: null,
      sections: {
        stem: {
          label: '题干',
          content: '已知函数 \\(f(x)=x^2+1\\)，判断其单调区间。',
          status: 'done',
          updatedAt: '2026-03-13T12:00:00.000Z',
          locked: false,
          edited: false,
        },
        answer: {
          label: '答案',
          content: '在区间 (0, +∞) 单调递增。',
          status: 'done',
          updatedAt: '2026-03-13T12:00:01.000Z',
          locked: false,
          edited: false,
        },
        analysis: {
          label: '解析',
          content: '先求导，再由导数符号判断单调性。',
          status: 'done',
          updatedAt: '2026-03-13T12:00:02.000Z',
          locked: false,
          edited: true,
        },
      },
    }

    const { container } = render(
      <MemoryRouter>
        <QuestionDraftCard draft={draft} sessionId="session-001" />
      </MemoryRouter>
    )

    expect(screen.getByText('题目 01')).toBeInTheDocument()
    expect(screen.getByText('题干')).toBeInTheDocument()
    expect(screen.getByText('答案')).toBeInTheDocument()
    expect(screen.getByText('解析')).toBeInTheDocument()
    expect(screen.getByText('待审查')).toBeInTheDocument()
    expect(screen.getByDisplayValue('已知函数 \\(f(x)=x^2+1\\)，判断其单调区间。')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '进入审查' })).toHaveAttribute('href', '/ai-generate/review/session-001/q-001')
    expect(screen.getByRole('button', { name: '审核通过并入库' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '重生成解析' })).toBeInTheDocument()
    expect(screen.getByText('已手动调整')).toBeInTheDocument()
    expect(container.querySelector('.katex')).not.toBeNull()
  })
})
