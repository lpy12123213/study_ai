import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStream } from '@/hooks/useChat'
import { useTaskStore } from '@/stores/useTaskStore'

const { sendMessageStreamMock } = vi.hoisted(() => ({
  sendMessageStreamMock: vi.fn(),
}))

vi.mock('@/api/chat', () => ({
  sendMessageStream: sendMessageStreamMock,
  getConversations: vi.fn(),
  getConversation: vi.fn(),
  getMessages: vi.fn(),
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
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

describe('useChatStream', () => {
  beforeEach(() => {
    resetTaskStore()
    sendMessageStreamMock.mockReset()
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('turns chat stream events into assistant message text and tool steps', async () => {
    sendMessageStreamMock.mockImplementation((_request, onEvent, _onError, onDone) => {
      onEvent({ type: 'text_delta', delta: 'Hel', raw: { type: 'text_delta' } })
      onEvent({
        type: 'tool_start',
        raw: {
          type: 'tool_start',
          tool_call_id: 'tool-1',
          tool_name: 'search',
          arguments: { q: '函数' },
        },
      })
      onEvent({
        type: 'tool_result',
        raw: {
          type: 'tool_result',
          tool_call_id: 'tool-1',
          tool_name: 'search',
          result: { success: true, hits: 2 },
        },
      })
      onEvent({
        type: 'assistant_final',
        raw: {
          type: 'assistant_final',
          content: 'Hello',
        },
      })
      onDone()
    })

    const { result } = renderHook(() => useChatStream(), { wrapper: createWrapper() })

    await act(async () => {
      result.current.sendMessage('conversation-1', '你好')
    })

    expect(sendMessageStreamMock).toHaveBeenCalledTimes(1)
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.streamingText).toBe('')
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0]).toMatchObject({
      role: 'user',
      content: '你好',
    })
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      content: 'Hello',
      steps: [
        {
          id: 'tool-1',
          status: 'completed',
          toolName: 'search',
          output: { success: true, hits: 2 },
        },
      ],
    })
  })
})
