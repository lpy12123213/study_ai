import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ChatPage from '@/pages/ChatPage'
import type { Message } from '@/types'

const hookMocks = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  cancelStream: vi.fn(),
  useMessages: vi.fn(),
  useChatStream: vi.fn(),
}))

const apiMocks = vi.hoisted(() => ({
  createConversation: vi.fn(),
}))

vi.mock('@/hooks/useChat', () => hookMocks)
vi.mock('@/api/chat', () => apiMocks)

vi.mock('@/components/shared/RichTextarea', () => ({
  RichTextarea: (props: {
    value: string
    onChange: (value: string) => void
    ariaLabel?: string
    disabled?: boolean
  }) => (
    <textarea
      aria-label={props.ariaLabel || 'input'}
      disabled={props.disabled}
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
    />
  ),
}))

vi.mock('@/features/chat/components/MessageBubble', () => ({
  MessageBubble: ({ message }: { message: Message }) => (
    <div data-testid={`message-${message.id}`}>{message.content}</div>
  ),
}))

vi.mock('@/features/chat/components/WelcomeScreen', () => ({
  WelcomeScreen: () => <div>Welcome</div>,
}))

function renderChatPage(initialEntry = '/chat/next') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/chat/:conversationId" element={<ChatPage />} />
        <Route path="/chat" element={<ChatPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('ChatPage', () => {
  beforeEach(() => {
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0)
      return 1
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    hookMocks.useMessages.mockReturnValue({
      messages: [],
      isLoading: true,
      hasNextPage: false,
      fetchNextPage: vi.fn(),
      isFetchingNextPage: false,
    })
    apiMocks.createConversation.mockResolvedValue({ id: 'created', title: '新对话' })
    hookMocks.useChatStream.mockReturnValue({
      messages: [
        {
          id: 'old-assistant',
          role: 'assistant',
          content: '上一会话的旧消息',
          createdAt: '2026-06-06T00:00:00.000Z',
        },
      ],
      setMessages: vi.fn(),
      streamingMessageId: '',
      streamingText: '',
      isStreaming: false,
      error: null,
      sendMessage: hookMocks.sendMessage,
      cancelStream: hookMocks.cancelStream,
    })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('does not render stale local messages before the current conversation is hydrated', () => {
    renderChatPage('/chat/next')

    expect(screen.queryByText('上一会话的旧消息')).not.toBeInTheDocument()
  })

  it('sends the first message from the newly mounted conversation route', async () => {
    const user = userEvent.setup()
    renderChatPage('/chat')

    await user.type(screen.getByLabelText('输入消息'), '请只回复 OK')
    await user.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => expect(apiMocks.createConversation).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(hookMocks.sendMessage).toHaveBeenCalledWith('created', '请只回复 OK'))
  })
})
