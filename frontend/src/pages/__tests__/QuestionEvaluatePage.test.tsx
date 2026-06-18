import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import QuestionEvaluatePage from '@/pages/QuestionEvaluatePage'

vi.mock('@/hooks/useSubjects', () => ({
  useSubjects: () => ({
    data: [{ id: '1', code: '高中数学', name: '高中数学' }],
  }),
}))

vi.mock('@/api/questionEvaluate', () => ({
  searchQuestions: vi.fn().mockResolvedValue({ success: true, questions: [] }),
  evaluateQuestions: vi.fn().mockResolvedValue({ results: [] }),
}))

vi.mock('@/components/shared/RichTextarea', () => ({
  RichTextarea: ({ value, onChange, placeholder, ariaLabel }: {
    value: string
    onChange: (v: string) => void
    placeholder?: string
    ariaLabel?: string
  }) => (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      aria-label={ariaLabel}
      data-testid="rich-textarea"
    />
  ),
}))

vi.mock('@/components/ui/scroll-area', () => ({
  ScrollArea: ({ children, className }: { children: ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}))

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <QuestionEvaluatePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('QuestionEvaluatePage', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('renders without crashing and shows title', () => {
    renderPage()
    expect(screen.getByText('题目诊断光谱仪')).toBeInTheDocument()
  })

  it('renders search and evaluate controls', () => {
    renderPage()
    // "鉴别结果" appears in both stats grid and CardTitle
    expect(screen.getAllByText('鉴别结果').length).toBeGreaterThan(0)
    expect(screen.getAllByText('搜索结果').length).toBeGreaterThan(0)
    expect(screen.getByText('额外要求（可选）')).toBeInTheDocument()
  })
})
