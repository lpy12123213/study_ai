import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { QuestionLibraryFilterBar } from '@/features/generation/questionLibrary/QuestionLibraryFilterBar'

describe('QuestionLibraryFilterBar', () => {
  afterEach(() => {
    cleanup()
  })

  it('exposes local question metadata quick filters', () => {
    const onExamSceneChange = vi.fn()
    const onQuestionTypeChange = vi.fn()
    const onDifficultyChange = vi.fn()
    const onCategoryChange = vi.fn()
    const onOnlyNewChange = vi.fn()
    const FilterBar = QuestionLibraryFilterBar as any

    render(
      <FilterBar
        subjects={[{ code: 'math', name: '数学' }]}
        filters={{
          subject: 'math',
          origin: 'crawled',
          hidden: '0',
          q: '',
          sort: 'updated_at',
          order: 'desc',
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
        }}
        onSubjectChange={vi.fn()}
        onOriginChange={vi.fn()}
        onHiddenChange={vi.fn()}
        onQueryChange={vi.fn()}
        onSortChange={vi.fn()}
        onOrderChange={vi.fn()}
        onRefresh={vi.fn()}
        onExamSceneChange={onExamSceneChange}
        onQuestionTypeChange={onQuestionTypeChange}
        onDifficultyChange={onDifficultyChange}
        onCategoryChange={onCategoryChange}
        onMoreFilterChange={vi.fn()}
        onOnlyNewChange={onOnlyNewChange}
      />
    )

    expect(screen.getByText('场景：')).not.toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '期末' }))
    fireEvent.click(screen.getByRole('button', { name: '单选题' }))
    fireEvent.click(screen.getByRole('button', { name: '容易' }))
    fireEvent.click(screen.getByRole('button', { name: '新文化题' }))
    fireEvent.click(screen.getByRole('checkbox', { name: '只看新题' }))

    expect(onExamSceneChange).toHaveBeenCalledWith('期末')
    expect(onQuestionTypeChange).toHaveBeenCalledWith('单选题')
    expect(onDifficultyChange).toHaveBeenCalledWith('容易')
    expect(onCategoryChange).toHaveBeenCalledWith('新文化题')
    expect(onOnlyNewChange).toHaveBeenCalledWith(true)
  })
})
