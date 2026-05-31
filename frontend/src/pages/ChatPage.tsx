import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { ChevronDown, Loader2, Send, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RichTextarea } from '@/components/shared/RichTextarea'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { LoadingSpinner } from '@/components/shared/LoadingSpinner'
import { useChatStream, useMessages } from '@/hooks/useChat'
import { useStickToBottom } from '@/hooks/useStickToBottom'
import { cn } from '@/lib/utils'
import * as chatApi from '@/api/chat'

import { MessageBubble } from '@/features/chat/components/MessageBubble'
import { WelcomeScreen } from '@/features/chat/components/WelcomeScreen'
import { useVirtualMessages } from '@/hooks/useVirtualMessages'
import type { Message } from '@/types'

export default function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const targetMid = String(searchParams.get('mid') || '').trim()
  const [highlightMid, setHighlightMid] = useState<string>('')
  const [input, setInput] = useState('')
  const hydratedConversationIdRef = useRef<string | null>(null)
  const lastConversationIdRef = useRef<string | undefined>(conversationId)
  const [isCreatingConversation, setIsCreatingConversation] = useState(false)
  const [createError, setCreateError] = useState<unknown>(null)
  const stick = useStickToBottom({ thresholdPx: 120 })

  const {
    messages: historyMessages,
    isLoading: isHistoryLoading,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useMessages(conversationId)
  const {
    messages,
    setMessages,
    streamingMessageId,
    streamingText,
    isStreaming,
    error,
    sendMessage,
    cancelStream,
  } = useChatStream()
  const shouldVirtualize = messages.length >= 500
  const virtual = useVirtualMessages({
    enabled: shouldVirtualize,
    messages,
    containerRef: stick.containerRef,
    estimatePx: 220,
    overscan: 12,
  })

  useEffect(() => {
    if (!targetMid) return
    setHighlightMid(targetMid)
    const t = window.setTimeout(() => setHighlightMid(''), 6000)
    return () => window.clearTimeout(t)
  }, [targetMid])

  useEffect(() => {
    if (!targetMid) return
    const exists = messages.some((m) => String(m.id) === targetMid)
    if (exists) return
    if (!hasNextPage || isFetchingNextPage) return
    fetchNextPage()
  }, [targetMid, messages, hasNextPage, isFetchingNextPage, fetchNextPage])

  useEffect(() => {
    if (!targetMid) return
    const exists = messages.some((m) => String(m.id) === targetMid)
    if (!exists) return
    stick.setShouldStick(false)
    window.setTimeout(() => {
      if (shouldVirtualize) {
        virtual.scrollToId(targetMid, 'smooth')
        return
      }
      const el = document.getElementById(`msg-${targetMid}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 50)
  }, [targetMid, messages, shouldVirtualize, stick, virtual.scrollToId])

  useEffect(() => {
    if (!conversationId) return
    if (!historyMessages) return
    if (isStreaming) return

    setMessages((prev) => {
      if (hydratedConversationIdRef.current !== conversationId) {
        hydratedConversationIdRef.current = conversationId
        return historyMessages
      }

      const seen = new Set(prev.map((m) => m.id))
      const older = historyMessages.filter((m) => !seen.has(m.id))
      if (older.length === 0) return prev
      return [...older, ...prev]
    })
  }, [conversationId, historyMessages, isStreaming, setMessages])

  useEffect(() => {
    const last = lastConversationIdRef.current
    if (last && conversationId && last !== conversationId) {
      hydratedConversationIdRef.current = null
      setMessages([])
      setCreateError(null)
    }
    if (last && !conversationId) {
      hydratedConversationIdRef.current = null
      setMessages([])
      setCreateError(null)
    }
    lastConversationIdRef.current = conversationId
  }, [conversationId, setMessages, setCreateError])

  const displayMessage = useCallback(
    (message: Message): Message => {
      if (!streamingMessageId || String(message.id) !== streamingMessageId) return message
      return { ...message, content: streamingText }
    },
    [streamingMessageId, streamingText]
  )

  useEffect(() => {
    stick.maybeStick()
  }, [messages, streamingText, stick.maybeStick])

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const text = input.trim()
    if (!text || isStreaming || isCreatingConversation) return

    setInput('')
    setCreateError(null)
    stick.setShouldStick(true)

    if (conversationId) {
      sendMessage(conversationId, text)
      return
    }

    setIsCreatingConversation(true)
    chatApi
      .createConversation({ title: '新对话' })
      .then((conv) => {
        const newId = conv.id
        hydratedConversationIdRef.current = newId
        navigate(`/chat/${newId}`, { replace: true })
        sendMessage(newId, text)
      })
      .catch((err) => {
        setCreateError(err)
      })
      .finally(() => {
        setIsCreatingConversation(false)
      })
  }

  return (
    <div className="h-full flex flex-col relative">
      {messages.length === 0 ? (
        conversationId ? (
          <div className="flex-1 flex items-center justify-center p-8">
            {isHistoryLoading ? (
              <LoadingSpinner size="lg" />
            ) : (
              <div className="text-sm text-muted-foreground">暂无消息</div>
            )}
          </div>
        ) : (
          <>
            <WelcomeScreen onExampleClick={(text) => setInput(text)} />
            {createError && (
              <div className="max-w-3xl mx-auto w-full px-4 pb-6">
                <ErrorNotice error={createError} title="创建对话失败" onClose={() => setCreateError(null)} />
              </div>
            )}
          </>
        )
      ) : (
        <div ref={stick.containerRef} className="flex-1 overflow-auto p-4 pb-32" onScroll={stick.onScroll}>
          <div className="max-w-3xl mx-auto py-6">
            {(hasNextPage || isFetchingNextPage) && (
              <div className="flex justify-center mb-4">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                >
                  {isFetchingNextPage ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : null}
                  加载更早消息
                </Button>
              </div>
            )}

            {shouldVirtualize ? (
              <div ref={virtual.listRef} className="relative" style={{ height: virtual.totalHeight }}>
                {messages.slice(virtual.range.start, virtual.range.end).map((message, i) => {
                  const index = virtual.range.start + i
                  const mid = String(message.id)
                  const top = virtual.offsets[index] ?? 0
                  return (
                    <div
                      key={message.id}
                      ref={virtual.getMeasureRef(mid)}
                      className="absolute left-0 right-0 flow-root"
                      style={{ transform: `translateY(${top}px)` }}
                    >
                      <div
                        id={`msg-${mid}`}
                        className={cn(
                          mid === highlightMid &&
                            'rounded-xl ring-2 ring-primary/20 ring-offset-2 ring-offset-background'
                        )}
                      >
                        <MessageBubble message={displayMessage(message)} disableMotion={true} />
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <AnimatePresence mode="popLayout">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    id={`msg-${String(message.id)}`}
                    className={cn(
                      String(message.id) === highlightMid && 'rounded-xl ring-2 ring-primary/20 ring-offset-2 ring-offset-background'
                    )}
                  >
                    <MessageBubble message={displayMessage(message)} disableMotion={false} />
                  </div>
                ))}
              </AnimatePresence>
            )}

            {isStreaming && !streamingText && messages[messages.length - 1]?.content === '' && (
              <div className="flex gap-3 mb-4 max-w-3xl">
                <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                   <Loader2 className="h-3 w-3 animate-spin text-primary" />
                </div>
                <div className="text-sm text-muted-foreground pt-0.5">
                   正在思考...
                </div>
              </div>
            )}

            {Boolean(error) && (
              <ErrorNotice error={error} title="生成失败" />
            )}
          </div>
        </div>
      )}

      {!stick.isNearBottom && messages.length > 0 && (
        <Button
          type="button"
          size="icon"
          variant="secondary"
          className="absolute right-6 bottom-28 z-20 h-10 w-10 rounded-full shadow"
          onClick={() => {
            stick.scrollToBottom('smooth')
            stick.setShouldStick(true)
          }}
          aria-label="回到底部"
        >
          <ChevronDown className="h-4 w-4" />
        </Button>
      )}

      <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-background via-background to-transparent pt-10">
        <div className="max-w-3xl mx-auto">
          <form onSubmit={handleSubmit} className="relative group">
            <div className="relative flex items-end gap-2 p-2 rounded-2xl border bg-background shadow-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 transition-all">
              <RichTextarea
                value={input}
                onChange={setInput}
                onSubmit={handleSubmit}
                submitOnEnter
                placeholder="输入消息..."
                ariaLabel="输入消息"
                debounceMs={0}
                minHeight={44}
                maxHeight={200}
                className="min-h-[44px] w-full border-0 bg-transparent shadow-none focus-within:ring-0"
                editorClassName="px-0 py-2.5 placeholder:text-muted-foreground/50"
                disabled={isStreaming || isCreatingConversation}
              />
              
              {isStreaming ? (
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  className="h-9 w-9 rounded-xl shrink-0 mb-0.5"
                  onClick={() => cancelStream('user_cancelled')}
                  aria-label="Stop generating"
                >
                  <Square className="h-4 w-4" />
                </Button>
              ) : (
                <>
                  <Button
                    type="submit"
                    size="icon"
                    className={cn(
                      "h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all",
                      input.trim() ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                    )}
                    disabled={!input.trim() || isCreatingConversation}
                    aria-label="Send message"
                  >
                    {isCreatingConversation ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                  </Button>
                </>
              )}
            </div>
          </form>
          
          <div className="text-center mt-2 text-[10px] text-muted-foreground/50">
            AI 生成的内容可能不准确，请核实重要信息。
          </div>
        </div>
      </div>
    </div>
  )
}
