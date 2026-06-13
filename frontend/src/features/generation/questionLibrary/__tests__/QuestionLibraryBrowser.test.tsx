import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QuestionLibraryBrowser } from '@/features/generation/questionLibrary/QuestionLibraryBrowser'

const testState = vi.hoisted(() => ({
  lib: null as any,
  bulkDeleteQuestionLibraryItems: vi.fn(),
  refreshList: vi.fn(),
  refreshDetail: vi.fn(),
  runCrawl: vi.fn(),
  runScore: vi.fn(),
}))

vi.mock('@/api/questionLibrary', () => ({
  bulkDeleteQuestionLibraryItems: testState.bulkDeleteQuestionLibraryItems,
}))

vi.mock('@/hooks/useSubjects', () => ({
  useSubjects: () => ({ data: [{ code: '高中数学', name: '高中数学' }] }),
}))

vi.mock('@/features/generation/questionLibrary/hooks/useQuestionLibrary', () => ({
  useQuestionLibrary: () => testState.lib,
}))

vi.mock('@/features/generation/questionLibrary/hooks/useQuestionLibraryTasks', () => ({
  useQuestionLibraryTasks: () => ({
    preferredTask: null,
    runCrawl: testState.runCrawl,
    runScore: testState.runScore,
  }),
}))

vi.mock('@/features/generation/questionLibrary/QuestionLibraryCard', () => ({
  QuestionLibraryCard: ({ item, bulk }: any) => {
    const id = String(item.question_id || '')
    return (
      <article data-testid={`question-${id}`}>
        <span>{item.stem || id}</span>
        {bulk ? (
          <button type="button" onClick={bulk.onToggle}>
            {bulk.selected ? `取消 ${id}` : `选择 ${id}`}
          </button>
        ) : null}
      </article>
    )
  },
}))

vi.mock('@/features/generation/questionLibrary/QuestionLibraryFilterBar', () => ({
  QuestionLibraryFilterBar: () => <div data-testid="filters" />,
}))

vi.mock('@/features/generation/questionLibrary/QuestionBar', () => ({
  QuestionBar: () => null,
}))

vi.mock('@/features/generation/questionLibrary/RunPanel', () => ({
  RunPanel: () => null,
}))

vi.mock('@/features/generation/questionLibrary/CrawlDialog', () => ({
  CrawlDialog: () => null,
}))

vi.mock('@/features/generation/questionLibrary/QuestionDetailDialog', () => ({
  QuestionDetailDialog: () => null,
}))

vi.mock('@/components/ui/scroll-area', () => ({
  ScrollArea: ({ children }: any) => <div>{children}</div>,
}))

function makeLib(items: Array<{ question_id: string; stem?: string }>) {
  return {
    filters: {
      subject: '高中数学',
      origin: 'crawled',
      hidden: '0',
      q: '',
      examScene: '',
      questionType: '',
      difficulty: '',
      category: '',
      year: '',
      region: '',
      grade: '',
      semester: '',
      method: '',
      onlyNew: false,
      sort: 'updated_at',
      order: 'desc',
    },
    setSubject: vi.fn(),
    setOrigin: vi.fn(),
    setHidden: vi.fn(),
    setQuery: vi.fn(),
    setExamScene: vi.fn(),
    setQuestionType: vi.fn(),
    setDifficulty: vi.fn(),
    setCategory: vi.fn(),
    setMoreFilter: vi.fn(),
    setOnlyNew: vi.fn(),
    setSort: vi.fn(),
    setOrder: vi.fn(),
    listQuery: { isFetching: false, isLoading: false, error: null },
    items,
    total: items.length,
    selectedId: '',
    setSelectedId: vi.fn(),
    selectedItem: null,
    detailQuery: { isLoading: false, error: null },
    detail: null,
    refreshList: testState.refreshList,
    refreshDetail: testState.refreshDetail,
  }
}

describe('QuestionLibraryBrowser bulk selection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('confirm', vi.fn(() => true))
    testState.bulkDeleteQuestionLibraryItems.mockResolvedValue({ success: true, deleted: 1 })
    testState.lib = makeLib([
      { question_id: 'q-visible', stem: 'visible stem' },
      { question_id: 'q-hidden', stem: 'hidden stem' },
    ])
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('deletes only selected questions that remain visible after filters change', async () => {
    const user = userEvent.setup()
    const view = render(<QuestionLibraryBrowser />)

    await user.click(screen.getByRole('button', { name: '批量删除' }))
    await user.click(screen.getByRole('button', { name: '选择 q-visible' }))
    await user.click(screen.getByRole('button', { name: '选择 q-hidden' }))
    expect(screen.getByRole('button', { name: /删除 \(2\)/ })).toBeEnabled()

    testState.lib = makeLib([{ question_id: 'q-visible', stem: 'visible stem' }])
    view.rerender(<QuestionLibraryBrowser />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /删除 \(1\)/ })).toBeEnabled()
    })

    await user.click(screen.getByRole('button', { name: /删除 \(1\)/ }))

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('1 道题'))
    expect(testState.bulkDeleteQuestionLibraryItems).toHaveBeenCalledWith(['q-visible'])
  })
})
