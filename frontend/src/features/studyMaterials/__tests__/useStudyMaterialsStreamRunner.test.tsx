import { act, renderHook } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { useConversationStore } from '@/stores/useConversationStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { useStudyMaterialsStreamRunner } from '@/features/studyMaterials/hooks/useStudyMaterialsStreamRunner'
import type { ConversationItem, Message } from '@/types'
import type { SubAgentActivity } from '@/features/studyMaterials/types'

const fetchSSERequestMock = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    fetchSSERequest: fetchSSERequestMock,
  }
})

function resetConversationStore() {
  useConversationStore.setState(
    {
      conversations: [],
      currentConversationIdByType: { blueprint: null, lesson_plan: null, study_materials: null },
      filter: 'all',
      messagesByConversation: {},
    } as any,
    true
  )
}

function resetTaskStore() {
  useTaskStore.setState({ activeTasks: new Map(), checkpoints: new Map() } as any)
}

describe('useStudyMaterialsStreamRunner', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fetchSSERequestMock.mockReset()

    localStorage.removeItem('conversation-storage')
    localStorage.removeItem('task-storage')

    resetConversationStore()
    resetTaskStore()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('appends text deltas into assistant message and clears active stream on done', () => {
    const now = new Date().toISOString()
    const conversationId = 'conv-1'
    const assistantMessageId = 'msg-a1'

    const conversation: ConversationItem = {
      id: conversationId,
      title: '新自学资料',
      type: 'study_materials',
      createdAt: now,
      updatedAt: now,
      status: 'active',
      resumable: false,
    }

    const assistantMessage: Message = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      createdAt: now,
    }

    useConversationStore.getState().addConversation(conversation)
    useConversationStore.getState().setCurrentConversation(conversationId, 'study_materials')
    useConversationStore.getState().setMessages(conversationId, [assistantMessage])

    const localTaskId = 'local-task-1'
    useTaskStore.getState().startTask(localTaskId)

    let subActivities: SubAgentActivity[] = []
    const setIsGeneratingLocal = vi.fn()
    const setError = vi.fn()
    const setActiveSubAgentTab = vi.fn()
    const setSubAgentActivities = vi.fn((updater: any) => {
      subActivities = typeof updater === 'function' ? updater(subActivities) : updater
    })

    const { result } = renderHook(() =>
      useStudyMaterialsStreamRunner({
        setIsGeneratingLocal,
        setError,
        setSubAgentActivities,
        setActiveSubAgentTab,
      })
    )

    act(() => {
      result.current.runStudyMaterialsStream({
        conversationId,
        assistantMessageId,
        request: { url: '/study-materials/generate/stream', method: 'POST', body: { topic: 'test' } },
        localTaskId,
      })
    })

    expect(fetchSSERequestMock).toHaveBeenCalledTimes(1)
    const onMessage = fetchSSERequestMock.mock.calls[0]?.[2] as (data: unknown) => void

    act(() => {
      onMessage({ type: 'task_started', data: { taskId: 'server-task-1' }, seq: 1 })
      onMessage({ type: 'text_delta', data: { content: 'Hello' }, seq: 2 })
      vi.advanceTimersByTime(120)
    })

    const updated = useConversationStore.getState().getMessages(conversationId).find((m) => m.id === assistantMessageId)
    expect(updated?.content).toBe('Hello')

    const runningConversation = useConversationStore.getState().conversations.find((c) => c.id === conversationId)
    expect(runningConversation?.resumable).toBe(true)
    expect(runningConversation?.activeStream?.taskId).toBe('server-task-1')

    act(() => {
      onMessage({ type: 'done', data: {}, seq: 3 })
    })

    const finishedConversation = useConversationStore.getState().conversations.find((c) => c.id === conversationId)
    expect(finishedConversation?.resumable).toBe(false)
    expect(finishedConversation?.activeStream).toBeUndefined()

    expect(useTaskStore.getState().activeTasks.has(localTaskId)).toBe(false)

    expect(setIsGeneratingLocal).toHaveBeenCalledWith(true)
    expect(setIsGeneratingLocal).toHaveBeenCalledWith(false)
    expect(setError).toHaveBeenCalledWith(null)
  })
})

