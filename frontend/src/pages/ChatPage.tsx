import { useState, useRef, useEffect } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, Loader2, Search, FileText, GraduationCap, Sparkles, ChevronDown, ChevronUp, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { LoadingSpinner } from '@/components/shared/LoadingSpinner'
import { useChatStream, useMessages } from '@/hooks/useChat'
import { useStickToBottom } from '@/hooks/useStickToBottom'
import { cn } from '@/lib/utils'
import { BrandMark } from '@/components/shared/BrandMark'
import * as chatApi from '@/api/chat'
import type { Message } from '@/types'

function MessageBubble({ message, disableMotion }: { message: Message; disableMotion: boolean }) {
  const isUser = message.role === 'user'
  const [showSteps, setShowSteps] = useState(false)

  if (isUser) {
    if (disableMotion) {
      return (
        <div className="flex justify-end mb-6">
          <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl bg-muted px-5 py-3 text-sm leading-6 text-foreground">
            <div className="whitespace-pre-wrap">{message.content}</div>
          </div>
        </div>
      )
    }
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex justify-end mb-6"
      >
        <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl bg-muted px-5 py-3 text-sm leading-6 text-foreground">
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>
      </motion.div>
    )
  }

  if (disableMotion) {
    return (
      <div className="flex flex-col gap-2 mb-8 max-w-3xl w-full">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
          <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center">
            <BrandMark size={12} />
          </div>
          <span>学习助手</span>
        </div>

        <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-7">
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>

        {message.steps && message.steps.length > 0 && (
          <div className="mt-3">
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs font-normal gap-1.5 bg-background hover:bg-muted/50"
              onClick={() => setShowSteps(!showSteps)}
            >
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              {showSteps ? '隐藏' : '查看'} {message.steps.length} 个思考步骤
              {showSteps ? <ChevronUp className="h-3 w-3 opacity-50" /> : <ChevronDown className="h-3 w-3 opacity-50" />}
            </Button>

            {showSteps && (
              <div className="mt-3 overflow-hidden rounded-lg border border-border bg-card">
                <div className="p-4 bg-muted/30">
                  <TaskTimeline steps={message.steps} />
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-2 mb-8 max-w-3xl w-full"
    >
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
        <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center">
          <BrandMark size={12} />
        </div>
        <span>学习助手</span>
      </div>
      
      <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-7">
        <div className="whitespace-pre-wrap">{message.content}</div>
      </div>

      {message.steps && message.steps.length > 0 && (
        <div className="mt-3">
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs font-normal gap-1.5 bg-background hover:bg-muted/50"
            onClick={() => setShowSteps(!showSteps)}
          >
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            {showSteps ? '隐藏' : '查看'} {message.steps.length} 个思考步骤
            {showSteps ? <ChevronUp className="h-3 w-3 opacity-50" /> : <ChevronDown className="h-3 w-3 opacity-50" />}
          </Button>

          <AnimatePresence>
            {showSteps && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="mt-3 overflow-hidden rounded-lg border border-border bg-card"
              >
                <div className="p-4 bg-muted/30">
                   <TaskTimeline steps={message.steps} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  )
}

function WelcomeScreen({ onExampleClick }: { onExampleClick: (text: string) => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 animate-in fade-in duration-500">
      <div className="mb-10 flex flex-col items-center text-center space-y-6">
        <div className="h-20 w-20 rounded-3xl bg-gradient-to-br from-primary/5 to-primary/10 flex items-center justify-center ring-1 ring-border/50 shadow-sm">
           <BrandMark size={48} />
        </div>
        <h2 className="text-2xl font-semibold tracking-tight">有什么我可以帮你的吗？</h2>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full">
        {[
          { icon: Search, title: '搜索真题', desc: '帮我搜索一些高考数学真题' },
          { icon: FileText, title: '生成试卷', desc: '生成一份初中物理力学测试卷' },
          { icon: GraduationCap, title: '生成自学资料', desc: '帮我生成一份“函数单调性”的自学资料' },
          { icon: Sparkles, title: '概念讲解', desc: '解释一下牛顿第三定律' },
        ].map((item) => (
          <button
            key={item.title}
            onClick={() => onExampleClick(item.desc)}
            className="group relative flex flex-col items-start p-4 h-auto text-left rounded-xl border bg-card hover:bg-accent/50 hover:border-accent transition-all duration-200 hover:-translate-y-0.5 shadow-sm hover:shadow-md"
          >
            <div className="mb-3 rounded-lg bg-muted p-2 group-hover:bg-background transition-colors">
              <item.icon className="h-4 w-4 text-muted-foreground group-hover:text-foreground" />
            </div>
            <div className="font-medium text-sm mb-1">{item.title}</div>
            <div className="text-xs text-muted-foreground line-clamp-2">{item.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

export default function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const targetMid = String(searchParams.get('mid') || '').trim()
  const [highlightMid, setHighlightMid] = useState<string>('')
  const [input, setInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
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
  const { messages, setMessages, isStreaming, error, sendMessage, cancelStream } = useChatStream()

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
      const el = document.getElementById(`msg-${targetMid}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 50)
  }, [targetMid, messages.length, stick])

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

  useEffect(() => {
    stick.maybeStick()
  }, [messages, stick.maybeStick])

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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
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

            {messages.length >= 500 ? (
              messages.map((message) => (
                <div
                  key={message.id}
                  id={`msg-${String(message.id)}`}
                  className={cn(
                    String(message.id) === highlightMid && 'rounded-xl ring-2 ring-primary/20 ring-offset-2 ring-offset-background'
                  )}
                >
                  <MessageBubble message={message} disableMotion={true} />
                </div>
              ))
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
                    <MessageBubble message={message} disableMotion={false} />
                  </div>
                ))}
              </AnimatePresence>
            )}

            {isStreaming && messages[messages.length - 1]?.content === '' && (
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
              <Textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入消息..."
                className="min-h-[44px] max-h-[200px] w-full resize-none border-0 bg-transparent py-2.5 px-0 focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50"
                disabled={isStreaming || isCreatingConversation}
                rows={1}
                style={{ height: 'auto', overflow: 'hidden' }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement;
                  target.style.height = 'auto';
                  target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
                }}
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
