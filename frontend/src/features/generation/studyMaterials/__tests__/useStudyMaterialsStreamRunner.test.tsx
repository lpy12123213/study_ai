import { act, renderHook } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { useConversationStore } from '@/stores/useConversationStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { useStudyMaterialsStreamRunner } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsStreamRunner'
import type { ConversationItem, Message } from '@/types'
import type { SubAgentActivity } from '@/features/generation/studyMaterials/types'

const { fetchSSERequestMock, streamTaskWsMock } = vi.hoisted(() => ({
  fetchSSERequestMock: vi.fn(),
  streamTaskWsMock: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    fetchSSERequest: fetchSSERequestMock,
  }
})

vi.mock('@/api/ws', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/ws')>()
  return {
    ...actual,
    streamTaskWs: streamTaskWsMock,
  }
})

function resetConversationStore() {
  useConversationStore.setState(
    {
      conversations: [],
      currentConversationIdByType: { blueprint: null, lesson_plan: null, study_materials: null },
      filter: 'all',
      messagesByConversation: {},
    } as unknown as Parameters<typeof useConversationStore.setState>[0]
  )
}

function resetTaskStore() {
  useTaskStore.setState({ activeTasks: new Map(), checkpoints: new Map() } as unknown as Parameters<typeof useTaskStore.setState>[0])
}

describe('useStudyMaterialsStreamRunner', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fetchSSERequestMock.mockReset()
    streamTaskWsMock.mockReset()

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
    const setSubAgentActivities = vi.fn((updater: SubAgentActivity[] | ((prev: SubAgentActivity[]) => SubAgentActivity[])) => {
      subActivities = typeof updater === 'function' ? (updater as (prev: SubAgentActivity[]) => SubAgentActivity[])(subActivities) : updater
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
      onMessage({
        type: 'done',
        data: { material: { error: { tool: 'compile_latex_to_pdf', error: 'compile boom' } } },
        seq: 3,
      })
    })

    const finishedConversation = useConversationStore.getState().conversations.find((c) => c.id === conversationId)
    expect(finishedConversation?.resumable).toBe(false)
    expect(finishedConversation?.activeStream).toBeUndefined()
    expect(finishedConversation?.status).toBe('completed')
    expect(finishedConversation?.lastTask).toMatchObject({
      taskType: 'study_materials',
      taskId: 'server-task-1',
      materialError: { tool: 'compile_latex_to_pdf', error: 'compile boom' },
    })

    expect(useTaskStore.getState().activeTasks.has(localTaskId)).toBe(false)

    expect(setIsGeneratingLocal).toHaveBeenCalledWith(true)
    expect(setIsGeneratingLocal).toHaveBeenCalledWith(false)
    expect(setError).toHaveBeenCalledWith(null)
  })

  it('marks the conversation failed with lastTask metadata on stream error events', () => {
    const now = new Date().toISOString()
    const conversationId = 'conv-err'
    const assistantMessageId = 'msg-err'

    useConversationStore.getState().addConversation({
      id: conversationId,
      title: '新自学资料',
      type: 'study_materials',
      createdAt: now,
      updatedAt: now,
      status: 'active',
      resumable: false,
    })
    useConversationStore.getState().setCurrentConversation(conversationId, 'study_materials')
    useConversationStore
      .getState()
      .setMessages(conversationId, [{ id: assistantMessageId, role: 'assistant', content: '', createdAt: now }])

    const setIsGeneratingLocal = vi.fn()
    const setError = vi.fn()

    const { result } = renderHook(() =>
      useStudyMaterialsStreamRunner({
        setIsGeneratingLocal,
        setError,
        setSubAgentActivities: vi.fn(),
        setActiveSubAgentTab: vi.fn(),
      })
    )

    act(() => {
      result.current.runStudyMaterialsStream({
        conversationId,
        assistantMessageId,
        request: { url: '/study-materials/generate/stream', method: 'POST', body: { topic: 'test' } },
      })
    })

    const onMessage = fetchSSERequestMock.mock.calls[0]?.[2] as (data: unknown) => void

    act(() => {
      onMessage({ type: 'task_started', data: { taskId: 'server-task-9' }, seq: 1 })
      onMessage({ type: 'error', data: { error: 'quality_gate_not_met' }, seq: 2 })
    })

    const conversation = useConversationStore.getState().conversations.find((c) => c.id === conversationId)
    expect(conversation?.status).toBe('failed')
    expect(conversation?.resumable).toBe(false)
    expect(conversation?.activeStream).toBeUndefined()
    expect(conversation?.lastTask).toMatchObject({ taskType: 'study_materials', taskId: 'server-task-9' })
    expect(setError).toHaveBeenCalledWith(expect.stringContaining('quality_gate_not_met'))
  })

  it('populates SubAgent activities from canonical task stream events', () => {
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

    let subActivities: SubAgentActivity[] = []
    const setIsGeneratingLocal = vi.fn()
    const setError = vi.fn()
    const setActiveSubAgentTab = vi.fn()
    const setSubAgentActivities = vi.fn((updater: SubAgentActivity[] | ((prev: SubAgentActivity[]) => SubAgentActivity[])) => {
      subActivities = typeof updater === 'function' ? (updater as (prev: SubAgentActivity[]) => SubAgentActivity[])(subActivities) : updater
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
        request: { url: '/tasks/server-task-1/stream?after_seq=0', method: 'GET' },
        initialTaskId: 'server-task-1',
      })
    })

    // Canonical task-stream URLs are routed through WebSocket (`streamTaskWs`)
    // for durable refresh-resume, not the regular SSE fetch path.
    expect(fetchSSERequestMock).not.toHaveBeenCalled()
    expect(streamTaskWsMock).toHaveBeenCalledTimes(1)
    const wsArgs = streamTaskWsMock.mock.calls[0]
    expect(wsArgs?.[0]).toBe('server-task-1')
    expect(wsArgs?.[1]).toBe(0)
    const onMessage = wsArgs?.[2] as (data: unknown) => void

    act(() => {
      onMessage({
        taskId: 'server-task-1',
        type: 'tool_call',
        data: {
          step_id: 'split-1',
          name: 'split_knowledge_points',
          title: '拆分知识点',
          arguments: { topic: '组合排列' },
        },
        seq: 1,
      })
      onMessage({
        taskId: 'server-task-1',
        type: 'tool_result',
        data: {
          step_id: 'split-1',
          name: 'split_knowledge_points',
          title: '拆分知识点',
          success: true,
          output: { knowledge_points: ['分类计数原理', '排列组合模型'] },
        },
        seq: 2,
      })
    })

    expect(subActivities.map((a) => ({ knowledgePoint: a.knowledgePoint, status: a.status, steps: a.steps }))).toEqual([
      { knowledgePoint: '分类计数原理', status: 'pending', steps: [] },
      { knowledgePoint: '排列组合模型', status: 'pending', steps: [] },
    ])

    act(() => {
      onMessage({
        taskId: 'server-task-1',
        type: 'subagent_start',
        data: { knowledge_point: '分类计数原理' },
        seq: 3,
      })
      onMessage({
        taskId: 'server-task-1',
        type: 'tool_call',
        data: {
          step_id: 'search-1',
          name: 'web_search_knowledge',
          title: '联网搜索资料',
          arguments: { knowledge_points: ['分类计数原理'], query: '分类计数原理' },
        },
        seq: 4,
      })
      onMessage({
        taskId: 'server-task-1',
        type: 'tool_result',
        data: {
          step_id: 'search-1',
          name: 'web_search_knowledge',
          title: '联网搜索资料',
          success: true,
          output: { results: [{ title: 'source' }] },
        },
        seq: 5,
      })
      onMessage({
        taskId: 'server-task-1',
        type: 'subagent_end',
        data: { knowledge_point: '分类计数原理' },
        seq: 6,
      })
    })

    const active = subActivities.find((a) => a.knowledgePoint === '分类计数原理')
    expect(setActiveSubAgentTab).toHaveBeenCalledWith('分类计数原理')
    expect(active?.status).toBe('completed')
    expect(active?.steps).toHaveLength(1)
    expect(active?.steps[0]).toMatchObject({
      id: 'search-1',
      title: '联网搜索资料',
      status: 'completed',
      toolName: 'web_search_knowledge',
      input: { knowledge_points: ['分类计数原理'], query: '分类计数原理' },
      output: { results: [{ title: 'source' }] },
    })
  })
})

