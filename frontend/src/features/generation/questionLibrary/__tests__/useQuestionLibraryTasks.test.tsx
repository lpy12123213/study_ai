import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useQuestionLibraryTasks } from '@/features/generation/questionLibrary/hooks/useQuestionLibraryTasks'
import { useTaskStore } from '@/stores/useTaskStore'

const apiMocks = vi.hoisted(() => ({
  crawlQuestions: vi.fn(),
  generateQuestions: vi.fn(),
  getLatestPendingQuestionLibraryPreview: vi.fn(),
  importMediaQuestions: vi.fn(),
}))

vi.mock('@/api/questionLibrary', () => ({
  crawlQuestions: apiMocks.crawlQuestions,
  generateQuestions: apiMocks.generateQuestions,
  getLatestPendingQuestionLibraryPreview: apiMocks.getLatestPendingQuestionLibraryPreview,
  importMediaQuestions: apiMocks.importMediaQuestions,
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

function filters() {
  return {
    subject: '高中数学',
    origin: 'ai' as const,
    hidden: '0' as const,
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
    sort: 'updated_at' as const,
    order: 'desc' as const,
  }
}

function resetTaskStore() {
  useTaskStore.setState({
    activeTasks: new Map(),
    checkpoints: new Map(),
  })
  window.localStorage.removeItem('task-storage')
}

describe('useQuestionLibraryTasks', () => {
  beforeEach(() => {
    resetTaskStore()
    vi.clearAllMocks()
    apiMocks.getLatestPendingQuestionLibraryPreview.mockResolvedValue({ success: true, preview: null })
  })

  it('keeps generation metadata on draftPreview from a done event', async () => {
    apiMocks.generateQuestions.mockImplementation((_payload, onEvent, _onError, onDone) => {
      onEvent({
        taskId: 'task-generate',
        seq: 1,
        type: 'done',
        data: {
          preview_id: 'preview-generate',
          session_id: 'session-generate',
          subject: '高中数学',
          topic: '导数压轴题',
          difficulty: '困难',
          question_type: '解答题',
          use_study_archive: true,
          use_reference_questions: false,
          count: 1,
          draft_questions: [
            {
              question_id: 'q-generate',
              stem: '题干',
              answer: '答案',
              analysis: '解析',
            },
          ],
        },
      })
      onDone()
    })

    const { result } = renderHook(() => useQuestionLibraryTasks({ filters: filters() }), { wrapper: createWrapper() })

    act(() => {
      result.current.runGenerate({
        subject: '高中数学',
        topic: '导数压轴题',
        difficulty: '困难',
        question_type: '解答题',
        use_study_archive: true,
      })
    })

    await waitFor(() => {
      expect(result.current.draftPreview?.previewId).toBe('preview-generate')
    })

    expect(result.current.draftPreview?.difficulty).toBe('困难')
    expect(result.current.draftPreview?.questionType).toBe('解答题')
    expect(result.current.draftPreview?.useStudyArchive).toBe(true)
  })

  it('keeps generation metadata when restoring the latest pending preview', async () => {
    apiMocks.getLatestPendingQuestionLibraryPreview.mockResolvedValue({
      success: true,
      preview: {
        preview_id: 'preview-latest',
        session_id: 'session-latest',
        task_id: 'task-latest',
        subject: '高中数学',
        topic: '圆锥曲线',
        mode: 'standard',
        difficulty: '困难',
        question_type: '解答题',
        use_study_archive: true,
        count: 1,
        draft_questions: [
          {
            question_id: 'q-latest',
            stem: '题干',
            answer: '答案',
            analysis: '解析',
          },
        ],
      },
    })

    const { result } = renderHook(() => useQuestionLibraryTasks({ filters: filters(), restoreLatestPreview: true }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.draftPreview?.previewId).toBe('preview-latest')
    })

    expect(result.current.draftPreview?.difficulty).toBe('困难')
    expect(result.current.draftPreview?.questionType).toBe('解答题')
    expect(result.current.draftPreview?.useStudyArchive).toBe(true)
  })
})
