import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useQuestionLibrary } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'

const apiMocks = vi.hoisted(() => ({
  getQuestionLibraryItem: vi.fn(),
  listQuestionLibrary: vi.fn(),
}))

vi.mock('@/api/questionLibrary', () => ({
  getQuestionLibraryItem: apiMocks.getQuestionLibraryItem,
  listQuestionLibrary: apiMocks.listQuestionLibrary,
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe('useQuestionLibrary filters', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listQuestionLibrary.mockResolvedValue({
      success: true,
      total: 0,
      include_total: true,
      items: [],
      limit: 80,
      offset: 0,
    })
  })

  it('passes local filter values to the backend list API contract', async () => {
    renderHook(
      () =>
        useQuestionLibrary({
          initialFilters: {
            subject: '高中数学',
            origin: 'crawled',
            hidden: '0',
            q: '函数',
            examScene: '期末',
            questionType: '单选题',
            difficulty: '容易',
            category: '新文化题',
            year: '2024',
            region: '北京',
            grade: '高三',
            semester: '期末',
            method: '分类讨论',
            onlyNew: true,
            sort: 'updated_at',
            order: 'desc',
          },
        }),
      { wrapper: createWrapper() }
    )

    await waitFor(() => {
      expect(apiMocks.listQuestionLibrary).toHaveBeenCalled()
    })

    expect(apiMocks.listQuestionLibrary).toHaveBeenCalledWith(
      expect.objectContaining({
        subject: '高中数学',
        origin: 'crawled',
        hidden: '0',
        q: '函数',
        exam_scene: '期末',
        question_type: '单选题',
        difficulty: '容易',
        category: '新文化题',
        year: '2024',
        region: '北京',
        grade: '高三',
        semester: '期末',
        method: '分类讨论',
        only_new: true,
        sort: 'updated_at',
        order: 'desc',
        limit: 80,
        offset: 0,
      })
    )
  })
})
