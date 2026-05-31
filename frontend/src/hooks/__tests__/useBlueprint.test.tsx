import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useComposePaper } from '@/hooks/useBlueprint'
import { useTaskStore } from '@/stores/useTaskStore'

const { composePaperStreamMock } = vi.hoisted(() => ({
  composePaperStreamMock: vi.fn(),
}))

vi.mock('@/api/blueprint', () => ({
  composePaperStream: composePaperStreamMock,
  pauseComposeTask: vi.fn(),
  resumeComposeTask: vi.fn(),
  streamComposeTask: vi.fn(),
  getBlueprints: vi.fn(),
  getBlueprint: vi.fn(),
  saveBlueprint: vi.fn(),
  deleteBlueprint: vi.fn(),
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

function resetTaskStore() {
  useTaskStore.setState({
    activeTasks: new Map(),
    checkpoints: new Map(),
  })
  window.localStorage.removeItem('task-storage')
}

describe('useComposePaper', () => {
  beforeEach(() => {
    resetTaskStore()
    composePaperStreamMock.mockReset()
  })

  it('deduplicates repeated stream steps and completes when a result arrives', async () => {
    composePaperStreamMock.mockImplementation((_request, onEvent, _onError, onDone) => {
      onEvent({
        type: 'step',
        seq: 1,
        step: { id: 'draft', title: '生成蓝图', status: 'running' },
      })
      onEvent({
        type: 'step',
        seq: 2,
        step: { id: 'draft', title: '生成蓝图', status: 'completed', output: { proposals: 3 } },
      })
      onEvent({ type: 'progress', seq: 3, progress: 99 })
      onEvent({
        type: 'result',
        seq: 4,
        result: { id: 101, title: '函数综合练习' },
      })
      onDone()
    })

    const { result } = renderHook(() => useComposePaper(), { wrapper: createWrapper() })

    await act(async () => {
      result.current.compose({
        subject: '高中数学',
        topic: '函数',
        slots: [],
      } as any)
    })

    expect(composePaperStreamMock).toHaveBeenCalledTimes(1)
    expect(result.current.isComposing).toBe(false)
    expect(result.current.progress).toBe(100)
    expect(result.current.result).toMatchObject({ id: 101, title: '函数综合练习' })
    expect(result.current.error).toBeNull()
    expect(useTaskStore.getState().getTaskSteps(result.current.taskId || '')).toHaveLength(0)
  })
})
