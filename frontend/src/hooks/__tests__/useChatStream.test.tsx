import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStream } from '@/hooks/useChat'
import { useTaskStore } from '@/stores/useTaskStore'
import type { ChatStreamEvent } from '@/api/chat'

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
    cleanup()
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

  it('surfaces assistant progress before final answer text arrives', async () => {
    let onEvent: ((event: ChatStreamEvent) => void) | undefined
    let onDone: (() => void) | undefined

    sendMessageStreamMock.mockImplementation((_request, handleEvent, _onError, handleDone) => {
      onEvent = handleEvent as (event: ChatStreamEvent) => void
      onDone = handleDone as () => void
    })

    const { result } = renderHook(() => useChatStream(), { wrapper: createWrapper() })

    await act(async () => {
      result.current.sendMessage('87', '生成一份学习计划')
    })

    expect(result.current.isStreaming).toBe(true)
    expect(result.current.streamingText).toBe('')

    await act(async () => {
      onEvent?.({
        type: 'assistant',
        raw: {
          type: 'assistant',
          content: '（第 1 轮：调用工具 search）',
          tool_calls: [],
          iteration: 1,
        },
      })
    })

    expect(result.current.streamingText).toBe('（第 1 轮：调用工具 search）')

    await act(async () => {
      onEvent?.({
        type: 'text_delta',
        delta: '最终',
        raw: { type: 'text_delta', content: '最终' },
      })
    })

    expect(result.current.streamingText).toBe('最终')

    await act(async () => {
      onEvent?.({
        type: 'assistant_final',
        raw: { type: 'assistant_final', content: '最终答案' },
      })
      onDone?.()
    })

    expect(result.current.streamingText).toBe('')
    expect(result.current.messages[1]).toMatchObject({
      role: 'assistant',
      content: '最终答案',
    })
  })

  it('drops the assistant placeholder when a progress-only stream completes', async () => {
    let onEvent: ((event: ChatStreamEvent) => void) | undefined
    let onDone: (() => void) | undefined

    sendMessageStreamMock.mockImplementation((_request, handleEvent, _onError, handleDone) => {
      onEvent = handleEvent as (event: ChatStreamEvent) => void
      onDone = handleDone as () => void
    })

    const { result } = renderHook(() => useChatStream(), { wrapper: createWrapper() })

    await act(async () => {
      result.current.sendMessage('88', '数学高考模拟')
    })

    await act(async () => {
      onEvent?.({
        type: 'stream_start',
        raw: { type: 'stream_start', iteration: 1 },
      })
    })

    expect(result.current.messages).toHaveLength(2)
    expect(result.current.streamingText).toBe('第 1 轮：正在规划回答...')

    await act(async () => {
      onDone?.()
    })

    expect(result.current.isStreaming).toBe(false)
    expect(result.current.streamingText).toBe('')
    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0]).toMatchObject({
      role: 'user',
      content: '数学高考模拟',
    })
  })

  it('does not abort an auto-started stream during React StrictMode effect replay', async () => {
    let signal: AbortSignal | undefined

    sendMessageStreamMock.mockImplementation((...args: unknown[]) => {
      const options = args[4] as { signal?: AbortSignal } | undefined
      signal = options?.signal
    })

    function AutoSendProbe() {
      const stream = useChatStream()
      const sentRef = React.useRef(false)

      React.useEffect(() => {
        if (sentRef.current) return
        sentRef.current = true
        stream.sendMessage('87', '自动发送')
      }, [stream])

      return null
    }

    const Wrapper = createWrapper()
    render(
      <React.StrictMode>
        <Wrapper>
          <AutoSendProbe />
        </Wrapper>
      </React.StrictMode>
    )

    await waitFor(() => expect(sendMessageStreamMock).toHaveBeenCalledTimes(1))

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10))
    })

    expect(signal?.aborted).toBe(false)
  })
})
