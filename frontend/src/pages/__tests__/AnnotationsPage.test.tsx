import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AnnotationsPage from '@/pages/AnnotationsPage'
import * as annotationsApi from '@/api/annotations'

vi.mock('@/api/annotations', () => ({
  exportAnnotations: vi.fn(),
  listAnnotations: vi.fn(),
  updateAnnotation: vi.fn(),
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
      <MemoryRouter initialEntries={['/annotations']}>
        <AnnotationsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AnnotationsPage', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows the empty state when filters remove all loaded annotations', async () => {
    vi.mocked(annotationsApi.listAnnotations).mockResolvedValue([
      {
        id: 1,
        item_type: 'paper',
        item_id: 'paper-1',
        anchor: '',
        tags: ['疑问', '已解决'],
        content: '这条已经解决',
      } as annotationsApi.Annotation,
    ])

    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('这条已经解决')).toBeInTheDocument()
    await user.click(screen.getByLabelText(/仅看未解决疑问/))

    await waitFor(() => {
      expect(screen.queryByText('这条已经解决')).not.toBeInTheDocument()
    })
    expect(screen.getByText('暂无批注。')).toBeInTheDocument()
  })
})
