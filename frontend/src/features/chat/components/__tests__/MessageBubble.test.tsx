import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MessageBubble } from '@/features/chat/components/MessageBubble'
import type { Message } from '@/types'

const markdownMock = vi.hoisted(() => ({
  Markdown: vi.fn(({ content }: { content?: string }) => <div data-testid="markdown">{content}</div>),
}))

vi.mock('@/components/shared/Markdown', () => markdownMock)

function message(role: Message['role'], content: string): Message {
  return {
    id: `${role}-1`,
    role,
    content,
    createdAt: '2026-06-08T00:00:00.000Z',
  }
}

describe('MessageBubble', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('renders assistant content through Markdown', () => {
    render(
      <MessageBubble
        disableMotion
        message={message('assistant', 'See [source](https://example.com) and ![plot](/api/media/generated/plot.svg).')}
      />
    )

    expect(screen.getByTestId('markdown')).toHaveTextContent('See [source](https://example.com)')
    expect(markdownMock.Markdown).toHaveBeenCalledWith(
      expect.objectContaining({
        content: expect.stringContaining('![plot](/api/media/generated/plot.svg)'),
      }),
      undefined,
    )
  })

  it('keeps user content as plain text', () => {
    render(<MessageBubble disableMotion message={message('user', '**not markdown**')} />)

    expect(screen.queryByTestId('markdown')).not.toBeInTheDocument()
    expect(screen.getByText('**not markdown**')).toBeInTheDocument()
    expect(markdownMock.Markdown).not.toHaveBeenCalled()
  })
})
