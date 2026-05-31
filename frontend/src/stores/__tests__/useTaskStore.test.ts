import { act } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useTaskStore } from '@/stores/useTaskStore'
import type { TaskStep } from '@/types'

function resetTaskStore() {
  useTaskStore.setState({
    activeTasks: new Map(),
    checkpoints: new Map(),
  })
  window.localStorage.removeItem('task-storage')
}

describe('useTaskStore', () => {
  beforeEach(() => {
    resetTaskStore()
  })

  it('tracks active task steps through update, pause, resume, and completion', () => {
    const step: TaskStep = {
      id: 'step-1',
      title: '检索资料',
      status: 'running',
      startTime: '2026-05-24T00:00:00.000Z',
    }

    act(() => {
      const store = useTaskStore.getState()
      store.startTask('task-1')
      store.addStep('task-1', step)
      store.updateStep('task-1', 'step-1', {
        output: { hits: 3 },
      })
      store.pauseTask('task-1')
    })

    const pausedSteps = useTaskStore.getState().getTaskSteps('task-1')
    expect(pausedSteps).toHaveLength(1)
    expect(pausedSteps[0]).toMatchObject({
      id: 'step-1',
      status: 'paused',
      output: { hits: 3 },
    })

    const checkpoint = useTaskStore.getState().resumeTask('task-1')
    expect(checkpoint).toMatchObject({
      taskId: 'task-1',
      status: 'paused',
      currentStep: 0,
      totalSteps: 1,
      canResume: true,
    })
    expect(checkpoint?.checkpoint.pendingSteps[0]).toMatchObject({
      id: 'step-1',
      status: 'pending',
    })

    act(() => {
      useTaskStore.getState().completeTask('task-1')
    })

    expect(useTaskStore.getState().getTaskSteps('task-1')).toHaveLength(0)
    expect(useTaskStore.getState().getCheckpoint('task-1')).toBeUndefined()
  })
})
