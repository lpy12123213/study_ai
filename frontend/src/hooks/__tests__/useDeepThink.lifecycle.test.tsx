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
})
