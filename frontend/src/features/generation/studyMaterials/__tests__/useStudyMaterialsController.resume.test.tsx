import React from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { useConversationStore } from '@/stores/useConversationStore'
import { useStudyMaterialsController } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsController'
import type { ConversationItem } from '@/types'

const {
  runStudyMaterialsStreamMock,
  abortActiveStreamMock,
  getStudyMaterialsTaskMock,
  streamKeyRef,
} = vi.hoisted(() => ({
  runStudyMaterialsStreamMock: vi.fn(),
  abortActiveStreamMock: vi.fn(),
  getStudyMaterialsTaskMock: vi.fn(),
  streamKeyRef: { current: null as string | null },
}))

vi.mock('@/features/generation/studyMaterials/hooks/useStudyMaterialsStreamRunner', () => {
  return {
    useStudyMaterialsStreamRunner: () => ({
      abortActiveStream: abortActiveStreamMock,
      runStudyMaterialsStream: runStudyMaterialsStreamMock,
      streamKeyRef,
    }),
  }
})

vi.mock('@/api/studyMaterials', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/studyMaterials')>()
  return {
    ...actual,
    getStudyMaterialsTask: getStudyMaterialsTaskMock,
  }
})

function resetConversationStore() {
  useConversationStore.setState(
    {
      conversations: [],
      currentConversationIdByType: { blueprint: null, lesson_plan: null, study_materials: null },
      filter: 'all',
      messagesByConversation: {},
    } as any
  )
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter initialEntries={['/study-materials']}>{children}</MemoryRouter>
}

describe('useStudyMaterialsController.resumeStudyMaterialsStreamWithProbe', () => {
  beforeEach(() => {
    runStudyMaterialsStreamMock.mockReset()
    abortActiveStreamMock.mockReset()
    getStudyMaterialsTaskMock.mockReset()
    streamKeyRef.current = null

    localStorage.removeItem('conversation-storage')
    resetConversationStore()
  })

  it('reconnects a running task stream from after_seq', async () => {
    const now = new Date().toISOString()
    const conversationId = 'conv-1'

    const conversation: ConversationItem = {
      id: conversationId,
      title: '新自学资料',
      type: 'study_materials',
      createdAt: now,
      updatedAt: now,
      status: 'active',
      resumable: false,
    }

    useConversationStore.getState().addConversation(conversation)
    useConversationStore.getState().setCurrentConversation(conversationId, 'study_materials')

    getStudyMaterialsTaskMock.mockResolvedValueOnce({ status: 'running' })

    const { result } = renderHook(() => useStudyMaterialsController(), { wrapper })

    await act(async () => {
      await result.current.resumeStudyMaterialsStreamWithProbe({
        conversationId,
        assistantMessageId: 'assistant-1',
        taskId: 'task-1',
        afterSeq: 42,
      })
    })

    expect(runStudyMaterialsStreamMock).toHaveBeenCalledTimes(1)
    const args = runStudyMaterialsStreamMock.mock.calls[0]?.[0]
    expect(args.conversationId).toBe(conversationId)
    expect(args.assistantMessageId).toBe('assistant-1')
    expect(args.initialTaskId).toBe('task-1')
    expect(args.initialSeq).toBe(42)
    expect(args.streamKey).toBe(`${conversationId}:task-1`)
    expect(args.request.method).toBe('GET')
    expect(args.request.url).toBe('/tasks/task-1/stream?after_seq=42')
  })

  it('replays a terminal task stream so refresh can receive the final event', async () => {
    const now = new Date().toISOString()
    const conversationId = 'conv-2'

    const conversation: ConversationItem = {
      id: conversationId,
      title: '新自学资料',
      type: 'study_materials',
      createdAt: now,
      updatedAt: now,
      status: 'failed',
      resumable: true,
      activeStream: {
        taskType: 'study_materials',
        taskId: 'task-2',
        assistantMessageId: 'assistant-2',
        lastSeq: 12,
      },
    } as any

    useConversationStore.getState().addConversation(conversation)
    useConversationStore.getState().setCurrentConversation(conversationId, 'study_materials')

    getStudyMaterialsTaskMock.mockResolvedValue({ status: 'completed', last_seq: 13 })
    runStudyMaterialsStreamMock.mockImplementation((opts) => {
      streamKeyRef.current = opts.streamKey || null
    })

    const { result } = renderHook(() => useStudyMaterialsController(), { wrapper })

    await waitFor(() => expect(runStudyMaterialsStreamMock).toHaveBeenCalled())
    const args = runStudyMaterialsStreamMock.mock.calls[0]?.[0]
    expect(args.conversationId).toBe(conversationId)
    expect(args.assistantMessageId).toBe('assistant-2')
    expect(args.initialTaskId).toBe('task-2')
    expect(args.initialSeq).toBe(12)
    expect(args.request.method).toBe('GET')
    expect(args.request.url).toBe('/tasks/task-2/stream?after_seq=12')
    expect(String(result.current.error || '')).toBe('')
  })

  it('silently clears stale active stream state when a terminal task has no new events', async () => {
    const now = new Date().toISOString()
    const conversationId = 'conv-terminal-stale'

    const conversation: ConversationItem = {
      id: conversationId,
      title: '新自学资料',
      type: 'study_materials',
      createdAt: now,
      updatedAt: now,
      status: 'failed',
      resumable: true,
      activeStream: {
        taskType: 'study_materials',
        taskId: 'task-terminal-stale',
        assistantMessageId: 'assistant-terminal-stale',
        lastSeq: 12,
      },
    } as any

    useConversationStore.getState().addConversation(conversation)
    useConversationStore.getState().setCurrentConversation(conversationId, 'study_materials')

    getStudyMaterialsTaskMock.mockResolvedValue({ status: 'failed', last_seq: 12 })

    const { result } = renderHook(() => useStudyMaterialsController(), { wrapper })

    await waitFor(() => {
      const updated = useConversationStore.getState().conversations.find((c) => c.id === conversationId) as any
      expect(updated?.activeStream).toBeUndefined()
    })

    expect(runStudyMaterialsStreamMock).not.toHaveBeenCalled()
    const updated = useConversationStore.getState().conversations.find((c) => c.id === conversationId) as any
    expect(updated?.resumable).toBe(false)
    expect(updated?.status).toBe('failed')
    expect(String(result.current.error || '')).toBe('')
  })

  it('marks the resumable stream as lost when the probe fails', async () => {
    const now = new Date().toISOString()
    const conversationId = 'conv-3'

    const conversation: ConversationItem = {
      id: conversationId,
      title: '新自学资料',
      type: 'study_materials',
      createdAt: now,
      updatedAt: now,
      status: 'failed',
      resumable: true,
      activeStream: {
        taskType: 'study_materials',
        taskId: 'task-3',
        assistantMessageId: 'assistant-3',
        lastSeq: 3,
      },
    } as any

    useConversationStore.getState().addConversation(conversation)
    useConversationStore.getState().setCurrentConversation(conversationId, 'study_materials')

    getStudyMaterialsTaskMock.mockRejectedValueOnce(new Error('boom'))

    const { result } = renderHook(() => useStudyMaterialsController(), { wrapper })

    await act(async () => {
      await result.current.resumeStudyMaterialsStreamWithProbe({
        conversationId,
        assistantMessageId: 'assistant-3',
        taskId: 'task-3',
        afterSeq: 3,
      })
    })

    expect(runStudyMaterialsStreamMock).toHaveBeenCalledTimes(0)

    const updated = useConversationStore.getState().conversations.find((c) => c.id === conversationId) as any
    expect(updated?.resumable).toBe(false)
    expect(updated?.activeStream).toBeUndefined()

    expect(String(result.current.error || '')).toContain('任务已丢失')
  })
})

