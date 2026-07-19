import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionRestore } from '@/features/generation/aiGenerate/hooks/useSessionRestore'

const apiMocks = vi.hoisted(() => ({
  listQuestionLibrarySessions: vi.fn(),
  getQuestionLibrarySession: vi.fn(),
  archiveQuestionLibrarySession: vi.fn(),
}))

vi.mock('@/api/questionLibrary', () => ({
  listQuestionLibrarySessions: apiMocks.listQuestionLibrarySessions,
  getQuestionLibrarySession: apiMocks.getQuestionLibrarySession,
  archiveQuestionLibrarySession: apiMocks.archiveQuestionLibrarySession,
}))

function createSessionDetail(overrides: Record<string, unknown> = {}) {
  return {
    session_id: 'session-running',
    preview_id: 'preview-running',
    status: 'running',
    mode: 'standard',
    subject: '高中数学',
    topic: '服务端初始任务',
    count: 5,
    task_ids: ['task-running'],
    latest_task_id: 'task-running',
    updated_at_s: 1710000000,
    created_at_s: 1710000000,
    reasoning_blocks_count: 0,
    confirmed_question_ids: [],
    stop_requested: false,
    difficulty: '中等',
    question_type: '填空题',
    use_study_archive: false,
    intuition_practice: {
      practice_goal: 'transfer',
      intuition_kinds: ['prediction', 'representation'],
      packet_size: 4,
      feedback_mode: 'reflective',
    },
    draft_questions: [],
    reasoning_blocks: [],
    task_events: [],
    ...overrides,
  }
}

function createWrapper(initialEntry = '/ai-generate?session=session-running') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
}

describe('useSessionRestore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listQuestionLibrarySessions.mockResolvedValue({ success: true, sessions: [] })
    apiMocks.archiveQuestionLibrarySession.mockResolvedValue({ success: true })
  })

  it('keeps user-edited composer values when the same session polls back with newer server metadata', async () => {
    apiMocks.getQuestionLibrarySession
      .mockResolvedValueOnce({
        success: true,
        session: createSessionDetail(),
      })
      .mockResolvedValueOnce({
        success: true,
        session: createSessionDetail({
          status: 'pending_review',
          topic: '服务端轮询旧任务',
          count: 1,
          difficulty: '简单',
          question_type: '选择题',
          use_study_archive: false,
          updated_at_s: 1710000100,
          draft_questions: [
            {
              question_id: 'q-polled',
              stem: '轮询回填题干',
              answer: '答案',
              analysis: '解析',
              keep: true,
            },
          ],
        }),
      })

    const tasks = {
      draftPreview: null,
      clearDraftPreview: vi.fn(),
    }

    const { result } = renderHook(
      () =>
        useSessionRestore({
          currentSubject: '高中数学',
          onSubjectChange: vi.fn(),
          tasks,
          pushToast: vi.fn(),
        }),
      { wrapper: createWrapper() }
    )

    await waitFor(() => {
      expect(result.current.missionText).toBe('服务端初始任务')
    })

    act(() => {
      result.current.setMissionText('用户刚改过的任务')
      result.current.setCount('9')
      result.current.setDifficulty('困难')
      result.current.setQuestionType('解答题')
      result.current.setUseStudyArchive(true)
      result.current.setIntuitionPractice({
        practice_goal: 'solution_appreciation',
        intuition_kinds: ['solution_comparison'],
        packet_size: 4,
        feedback_mode: 'guided',
      })
    })

    await act(async () => {
      await result.current.sessionDetailQuery.refetch()
    })

    await waitFor(() => {
      expect(result.current.session?.status).toBe('pending_review')
    })

    expect(result.current.session?.drafts[0]?.sections.stem.content).toBe('轮询回填题干')
    expect(result.current.missionText).toBe('用户刚改过的任务')
    expect(result.current.count).toBe('9')
    expect(result.current.difficulty).toBe('困难')
    expect(result.current.questionType).toBe('解答题')
    expect(result.current.useStudyArchive).toBe(true)
    expect(result.current.intuitionPractice.practice_goal).toBe('solution_appreciation')
    expect(result.current.intuitionPractice.intuition_kinds).toEqual(['solution_comparison'])
  })
})
