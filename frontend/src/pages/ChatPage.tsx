import { useState, useRef, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, Loader2, Search, FileText, GraduationCap, Sparkles, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { useChatStream, useMessages } from '@/hooks/useChat'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn } from '@/lib/utils'
import { BrandMark } from '@/components/shared/BrandMark'
import type { Message } from '@/types'

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const [showSteps, setShowSteps] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "flex gap-3 mb-4",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      <div
        className={cn(
          "h-8 w-8 rounded-full flex items-center justify-center shrink-0",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-foreground text-background"
        )}
      >
        {isUser ? (
          <User className="h-4 w-4" strokeWidth={1.8} />
        ) : (
          <Sparkles className="h-4 w-4" strokeWidth={1.8} />
        )}
      </div>

      <div
        className={cn(
          "max-w-[70%] rounded-2xl px-4 py-3",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted"
        )}
      >
        <div className="text-sm whitespace-pre-wrap">{message.content}</div>

        {message.steps && message.steps.length > 0 && (
          <div className="mt-2 pt-2 border-t border-border/50">
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-xs px-2"
              onClick={() => setShowSteps(!showSteps)}
            >
              <Sparkles className="h-3 w-3 mr-1" />
              {showSteps ? '隐藏' : '查看'} {message.steps.length} 个执行步骤
            </Button>

            <AnimatePresence>
              {showSteps && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="mt-2 overflow-hidden"
                >
                  <TaskTimeline steps={message.steps} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
    </motion.div>
  )
}

function WelcomeScreen() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
      <BrandMark size={64} className="mb-6" />
      <h2 className="text-2xl font-bold mb-2">你好！我是试卷助手</h2>
      <p className="text-muted-foreground max-w-md mb-8">
        我可以帮你搜索题目、组建试卷、生成教案，或者回答任何学科相关的问题。
      </p>

      <div className="grid grid-cols-2 gap-3 max-w-xl w-full">
        {[
          { icon: Search, title: '搜索真题', desc: '帮我搜索一些高考数学真题' },
          { icon: FileText, title: '生成试卷', desc: '生成一份初中物理力学测试卷' },
          { icon: GraduationCap, title: '生成教案', desc: '帮我写一份语文阅读课的教案' },
          { icon: Sparkles, title: '概念讲解', desc: '解释一下牛顿第三定律' },
        ].map((item) => {
          const Icon = item.icon
          return (
            <button
              key={item.title}
              className={cn(
                'group text-left p-4 rounded-xl border border-border/80',
                'bg-card/50 hover:bg-accent/60 transition-colors',
                'shadow-sm hover:shadow'
              )}
            >
              <div className="flex items-center gap-2 mb-2">
                <div className="h-8 w-8 rounded-lg bg-muted/60 flex items-center justify-center ring-1 ring-border/60 group-hover:bg-muted">
                  <Icon className="h-4 w-4 text-foreground/80" strokeWidth={1.8} />
                </div>
                <div className="font-medium text-sm">{item.title}</div>
              </div>
              <div className="text-sm text-muted-foreground leading-5">
                {item.desc}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const { data: historyMessages } = useMessages(conversationId)
  const { messages, setMessages, isStreaming, error, sendMessage } = useChatStream(
    conversationId || 'new'
  )

  const activeTasks = useTaskStore((state) => state.activeTasks)

  useEffect(() => {
    if (historyMessages) {
      setMessages(historyMessages)
    }
  }, [historyMessages, setMessages])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!input.trim() || isStreaming) return

    sendMessage(input.trim())
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const hasActiveTasks = Array.from(activeTasks.values()).some((steps) =>
    steps.some((s) => s.status === 'running')
  )

  return (
    <div className="h-full flex flex-col">
      {messages.length === 0 ? (
        <WelcomeScreen />
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-auto p-4">
          <div className="max-w-3xl mx-auto">
            <AnimatePresence mode="popLayout">
              {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
            </AnimatePresence>

            {isStreaming && messages[messages.length - 1]?.content === '' && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex gap-3 mb-4"
              >
                <div className="h-8 w-8 rounded-full bg-foreground text-background flex items-center justify-center">
                  <Loader2 className="h-4 w-4 text-background animate-spin" />
                </div>
                <div className="bg-muted rounded-2xl px-4 py-3">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    正在思考...
                  </div>
                </div>
              </motion.div>
            )}

            {error && (
              <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 mb-4">
                <p className="text-sm text-destructive">{error}</p>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="border-t border-border p-4 glass">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
          <div className="relative">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入消息... (Shift+Enter 换行)"
              className="min-h-[60px] max-h-[200px] pr-12 resize-none"
              disabled={isStreaming}
            />
            <Button
              type="submit"
              size="icon"
              className="absolute right-2 bottom-2"
              disabled={!input.trim() || isStreaming}
            >
              {isStreaming ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </div>

          {hasActiveTasks && (
            <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="secondary" className="gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                任务执行中
              </Badge>
              <span>右侧面板查看详情</span>
            </div>
          )}
        </form>
      </div>
    </div>
  )
}
