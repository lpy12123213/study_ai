import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useDeepThink } from '@/hooks/useDeepThink'

const { cancelTaskMock, solveDeepThinkStreamMock } = vi.hoisted(() => ({
  cancelTaskMock: vi.fn(),
  solveDeepThinkStreamMock: vi.fn(),
}))

vi.mock('@/api/tasks', () => ({
  cancelTask: cancelTaskMock,
}))

vi.mock('@/api/deepthink', () => ({
  solveDeepThinkStream: solveDeepThinkStreamMock,
}))

describe('useDeepThink lifecycle', () => {
  beforeEach(() => {
    cancelTaskMock.mockReset()
    cancelTaskMock.mockResolvedValue(undefined)
    solveDeepThinkStreamMock.mockReset()
    solveDeepThinkStreamMock.mockImplementation((_request, onEvent) => {
      onEvent({
        taskId: 'deepthink-1',
        type: 'search_start',
        question: '1+1=?',
        subject: '高中数学',
        config: {},
      })
    })
  })

  it('disconnects on unmount without canceling the backend task', async () => {
    const { result, unmount } = renderHook(() => useDeepThink())

    await act(async () => {
      result.current.solve('1+1=?', { subject: '高中数学' })
    })

    unmount()

    expect(cancelTaskMock).not.toHaveBeenCalled()
  })

  it('does not let a repeated node_generated event reset an evaluated node status', async () => {
    solveDeepThinkStreamMock.mockImplementation((_request, onEvent) => {
      onEvent({ taskId: 'deepthink-1', type: 'search_start', config: {} })
      onEvent({
        taskId: 'deepthink-1',
        type: 'node_generated',
        node: { id: 'n1', content: '第一步', status: 'generated' },
      })
      onEvent({
        taskId: 'deepthink-1',
        type: 'node_evaluated',
        nodeId: 'n1',
        status: 'evaluated',
        score: 0.8,
      })
      onEvent({
        taskId: 'deepthink-1',
        type: 'node_generated',
        node: { id: 'n1', content: '第一步更新', status: 'generated' },
      })
    })

    const { result } = renderHook(() => useDeepThink())

    await act(async () => {
      result.current.solve('1+1=?', { subject: '高中数学' })
    })

    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(resolve))
    })

    expect(result.current.nodes.n1?.status).toBe('evaluated')
    expect((result.current.nodes.n1 as any)?.content).toBe('第一步更新')
  })
})
