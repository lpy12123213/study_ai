import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DeepThinkPage from '@/pages/DeepThinkPage'

vi.mock('@/hooks/useSubjects', () => ({
  useSubjects: () => ({
    data: [
      { id: '1', code: '高中数学', name: '高中数学' },
      { id: '2', code: '高中物理', name: '高中物理' },
    ],
  }),
}))

vi.mock('@/hooks/useDeepThink', () => ({
  useDeepThink: () => ({
    status: 'idle',
    taskId: '',
    nodes: {},
    bestPath: [],
    answer: '',
    metrics: { totalNodes: 0, currentDepth: 0, bestScore: 0, elapsed: 0 },
    error: '',
    config: null,
    solve: vi.fn(),
    cancel: vi.fn(),
    reset: vi.fn(),
  }),
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

vi.mock('@/components/deepthink/ThinkingTree', () => ({
  ThinkingTree: () => <div data-testid="thinking-tree" />,
}))

vi.mock('@/components/task/TaskProgressHeader', () => ({
  TaskProgressHeader: () => <div data-testid="task-progress-header" />,
}))

vi.mock('framer-motion', () => ({
  AnimatePresence: ({ children }: { children: ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: { children?: ReactNode; [key: string]: unknown }) => (
      <div {...(props as Record<string, unknown>)}>{children}</div>
    ),
  },
}))

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DeepThinkPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DeepThinkPage', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('renders welcome screen when no messages', () => {
    const { container } = renderPage()
    // Welcome screen is shown when messages are empty; page must render without crashing
    expect(container.firstChild).toBeTruthy()
  })

  it('renders composer with input and action buttons', () => {
    renderPage()
    expect(screen.getByTestId('rich-textarea')).toBeInTheDocument()
    // Composer has attach + clear + submit buttons
    expect(screen.getByTitle('学科 / 题图')).toBeInTheDocument()
    expect(screen.getByTitle('清空对话')).toBeInTheDocument()
  })
})
