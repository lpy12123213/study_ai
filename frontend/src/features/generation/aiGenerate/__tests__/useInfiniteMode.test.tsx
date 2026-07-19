import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useInfiniteMode } from '@/features/generation/aiGenerate/hooks/useInfiniteMode'

describe('useInfiniteMode', () => {
  it('sends the default intuition practice contract through the existing generation request', () => {
    const runGenerate = vi.fn(() => 'task-001')
    const setSession = vi.fn()

    const { result } = renderHook(() =>
      useInfiniteMode({
        subject: '高中数学',
        pushToast: vi.fn(),
        tasks: { runGenerate, draftPreview: null },
        mode: 'standard',
        setMode: vi.fn(),
        session: null,
        setSession: setSession as any,
        activeSessionId: '',
        setSearchParams: vi.fn(),
        syncSessionFromServer: vi.fn(async () => null),
        optimisticStopRequestedRef: { current: null },
        missionText: '训练函数图像的结构直觉',
        difficulty: '中等',
        questionType: '解答题',
        count: '3',
        useStudyArchive: true,
        useReferenceQuestions: false,
        referenceSource: 'any',
        referenceYearRange: 'all',
        gradeId: 'grade-1',
        textbookVersionId: 'textbook-1',
        selectedKnowledgePointIds: ['kp-1'],
        selectedKnowledgeNodeLabels: ['函数单调性'],
        intuitionPractice: {
          practice_goal: 'structural_intuition',
          intuition_kinds: ['prediction', 'representation', 'invariant'],
          packet_size: 3,
          feedback_mode: 'guided',
        },
        isGenerating: false,
      })
    )

    act(() => result.current.startGeneration())

    expect(runGenerate).toHaveBeenCalledWith(
      expect.objectContaining({
        intuition_practice: {
          practice_goal: 'structural_intuition',
          intuition_kinds: ['prediction', 'representation', 'invariant'],
          packet_size: 3,
          feedback_mode: 'guided',
        },
      })
    )
    expect(setSession).toHaveBeenCalled()
  })
})
