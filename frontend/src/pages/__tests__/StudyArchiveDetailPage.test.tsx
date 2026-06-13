import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import StudyArchiveDetailPage from '@/pages/StudyArchiveDetailPage'

const studyArchiveMocks = vi.hoisted(() => ({
  getStudyArchive: vi.fn(),
}))

const metaMocks = vi.hoisted(() => ({
  getMeta: vi.fn(),
  setMeta: vi.fn(),
}))

vi.mock('@/api/studyArchives', () => ({
  getStudyArchive: studyArchiveMocks.getStudyArchive,
}))

vi.mock('@/api/meta', () => metaMocks)

vi.mock('@/api/tasks', () => ({
  exportStudyArchiveTask: vi.fn(),
}))

vi.mock('@/api/learningPlans', () => ({
  createLearningPlanFromStudyArchive: vi.fn(),
}))

vi.mock('@/components/ui/scroll-area', () => ({
  ScrollArea: ({ children, className }: { children: ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}))

vi.mock('@/components/shared/Markdown', () => ({
  Markdown: ({ markdown }: { markdown?: string }) => <div>{markdown}</div>,
}))

vi.mock('@/components/shared/ShareLinkDialog', () => ({
  ShareLinkDialog: () => null,
}))

vi.mock('@/components/shared/AnnotationDialog', () => ({
  AnnotationDialog: () => null,
}))

vi.mock('@/components/shared/TagEditDialog', () => ({
  TagEditDialog: () => null,
  useTagEditor: () => ({
    isOpen: false,
    value: '',
    setValue: vi.fn(),
    open: vi.fn(),
    close: vi.fn(),
    save: vi.fn(),
  }),
}))

function renderPage(initialEntry = '/study-archives/42') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/study-archives/:archiveId" element={<StudyArchiveDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('StudyArchiveDetailPage', () => {
  beforeEach(() => {
    studyArchiveMocks.getStudyArchive.mockResolvedValue({
      id: 42,
      subject: '高中数学',
      topic: '函数单调性',
      markdown: '',
      sections: [
        {
          title: '单调性的判断',
          content: '导数大于零时函数递增。',
        },
      ],
    })
    metaMocks.getMeta.mockResolvedValue({ starred: false, pinned: false, tags: [] })
    metaMocks.setMeta.mockResolvedValue({ starred: false, pinned: false, tags: [] })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders archive content in the Aurora theatre reading surface', async () => {
    const { container } = renderPage()

    expect(await screen.findByText('单调性的判断')).toBeInTheDocument()

    await waitFor(() => {
      expect(container.querySelector('.aurora-reading-theater')).toBeInTheDocument()
      expect(container.querySelector('.aurora-reading-body')).toBeInTheDocument()
    })
  })
})
