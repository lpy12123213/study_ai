import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QuestionDraftCard } from '@/features/generation/aiGenerate/QuestionDraftCard'
import type { AiGenerateDraftCard } from '@/features/generation/aiGenerate/types'

const clientMocks = vi.hoisted(() => ({
  downloadObjectUrl: vi.fn(),
  resolveApiResourceUrl: vi.fn((url: string) => `https://example.test${url.startsWith('/') ? url : `/${url}`}`),
}))

vi.mock('@/api/client', () => ({
  downloadObjectUrl: clientMocks.downloadObjectUrl,
  resolveApiResourceUrl: clientMocks.resolveApiResourceUrl,
}))

describe('QuestionDraftCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    clientMocks.downloadObjectUrl.mockResolvedValue({
      objectUrl: 'blob:diagram-1',
      revoke: vi.fn(),
    })
  })

  it('renders all artifact sections and loads generated diagrams through authenticated blob URLs', async () => {
    const diagramUrl = `/api/media/generated/${'a'.repeat(64)}.png`
    const draft: AiGenerateDraftCard = {
      id: 'draft-card-1',
      questionId: 'q-001',
      title: '题目 01',
      index: 0,
      keep: true,
      status: 'ready',
      reviewStatus: 'pending_review',
      review: null,
      diagrams: [
        {
          url: diagramUrl,
          alt: '双轨模型实验装置示意图',
          caption: '图1: 双轨模型实验装置图',
        },
      ],
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
    expect(await screen.findByRole('textbox', { name: '题干' })).toHaveTextContent('已知函数')
    expect(screen.getByRole('link', { name: '进入审查' })).toHaveAttribute('href', '/ai-generate/review/session-001/q-001')
    expect(screen.getByRole('button', { name: '审核通过并入库' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '重生成解析' })).toBeInTheDocument()
    expect(screen.getByText('已手动调整')).toBeInTheDocument()
    expect(screen.getByText('图1: 双轨模型实验装置图')).toBeInTheDocument()
    const diagram = await screen.findByAltText('双轨模型实验装置示意图')
    await waitFor(() => expect(diagram).toHaveAttribute('src', 'blob:diagram-1'))
    expect(clientMocks.downloadObjectUrl).toHaveBeenCalledWith(diagramUrl)
    expect(container.querySelector('.katex')).not.toBeNull()
  })
})
