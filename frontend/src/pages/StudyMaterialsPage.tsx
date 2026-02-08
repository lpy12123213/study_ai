import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { BookOpen, Loader2, Plus, Send, Sparkles, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { BrandMark } from '@/components/shared/BrandMark'
import { fetchSSE } from '@/api/client'
import { useConversationStore } from '@/stores/useConversationStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn, generateId } from '@/lib/utils'
import type { ConversationItem, Message, TaskStep } from '@/types'

type StudyMaterialsAgentEvent =
  | { event: 'thinking'; data: { content?: unknown } }
  | { event: 'tool_call'; data: { name?: unknown; arguments?: unknown } }
  | { event: 'content'; data: { content?: unknown; section?: unknown } }
  | { event: 'done'; data: { material?: unknown } }
  | { event: 'error'; data: { message?: unknown } }
  | { event: string; data?: unknown }

function toText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function toConversationTitle(text: string): string {
  const t = (text || '').trim()
  if (!t) return '新自学资料'
  return t.length > 18 ? `${t.slice(0, 18)}…` : t
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const [showSteps, setShowSteps] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn('flex gap-3 mb-4', isUser ? 'flex-row-reverse' : 'flex-row')}
    >
      <div
        className={cn(
          'h-8 w-8 rounded-full flex items-center justify-center shrink-0',
          isUser ? 'bg-primary text-primary-foreground' : 'bg-foreground text-background'
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
          'max-w-[75%] rounded-2xl px-4 py-3',
          isUser ? 'bg-primary text-primary-foreground' : 'bg-muted'
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
      <h2 className="text-2xl font-bold mb-2">自学资料生成（对话框 + Manus 时间线）</h2>
      <p className="text-muted-foreground max-w-md mb-8">
        直接像 ChatGPT 一样输入你想学的知识点（例如“函数单调性”），系统会自动检索题目、生成讲解与例题步骤，并输出 Markdown。
      </p>
      <div className="grid grid-cols-2 gap-3 max-w-xl w-full">
        {[
          { title: '函数单调性', desc: '高中数学：定义法与典型例题' },
          { title: '二次函数最值', desc: '配方法/判别式/图像理解' },
          { title: '受力分析', desc: '受力图、正交分解、常见陷阱' },
          { title: '化学平衡常数', desc: 'K 的表达式、比较与计算' },
        ].map((item) => (
          <div
            key={item.title}
            className={cn(
              'text-left p-4 rounded-xl border border-border/80',
              'bg-card/50 shadow-sm'
            )}
          >
            <div className="flex items-center gap-2 mb-2">
              <div className="h-8 w-8 rounded-lg bg-muted/60 flex items-center justify-center ring-1 ring-border/60">
                <BookOpen className="h-4 w-4 text-foreground/80" strokeWidth={1.8} />
              </div>
              <div className="font-medium text-sm">{item.title}</div>
            </div>
            <div className="text-sm text-muted-foreground leading-5">{item.desc}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function StudyMaterialsPage() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const [input, setInput] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const conversations = useConversationStore((state) => state.conversations)
  const currentConversationId = useConversationStore((state) => state.currentConversationId)
  const addConversation = useConversationStore((state) => state.addConversation)
  const setCurrentConversation = useConversationStore((state) => state.setCurrentConversation)
  const updateConversation = useConversationStore((state) => state.updateConversation)
  const setMessages = useConversationStore((state) => state.setMessages)
  const addMessage = useConversationStore((state) => state.addMessage)

  const activeConversationId = useMemo(() => {
    if (!currentConversationId) return null
    const current = conversations.find((c) => c.id === currentConversationId)
    // Reuse existing conversation type `lesson_plan` as “自学资料”
    return current?.type === 'lesson_plan' ? currentConversationId : null
  }, [conversations, currentConversationId])

  const messages = useConversationStore((state) =>
    state.getMessages(activeConversationId ?? '')
  )

  const {
    startTask,
    addStep,
    updateStep,
    completeTask,
    failTask,
  } = useTaskStore()

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages.length])

  const handleNewConversation = () => {
    const id = generateId()
    const now = new Date().toISOString()
    const item: ConversationItem = {
      id,
      title: '新自学资料',
      type: 'lesson_plan',
      createdAt: now,
      updatedAt: now,
      status: 'active',
      resumable: false,
    }
    addConversation(item)
    setCurrentConversation(id)
    setMessages(id, [])
    setInput('')
    setError(null)
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const prompt = input.trim()
    if (!prompt || isGenerating) return

    const now = new Date().toISOString()

    // Ensure a study-materials conversation is selected (reuse lesson_plan type)
    let conversationId = activeConversationId
    if (!conversationId) {
      conversationId = generateId()
      const conversation: ConversationItem = {
        id: conversationId,
        title: toConversationTitle(prompt),
        type: 'lesson_plan',
        createdAt: now,
        updatedAt: now,
        status: 'active',
        resumable: false,
        progress: 0,
      }
      addConversation(conversation)
      setCurrentConversation(conversationId)
      setMessages(conversationId, [])
    } else {
      updateConversation(conversationId, { updatedAt: now, status: 'active' })
    }

    addMessage(conversationId, {
      id: generateId(),
      role: 'user',
      content: prompt,
      createdAt: now,
    })

    setInput('')
    setError(null)

    const assistantMessageId = generateId()
    addMessage(conversationId, {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      createdAt: now,
      steps: [],
    })

    const taskId = `study-materials-${conversationId}-${Date.now()}`
    startTask(taskId)
    setIsGenerating(true)

    let runningStepId: string | null = null
    let done = false
    let assistantSteps: TaskStep[] = []
    let assistantText = ''
    let pendingText = ''
    let flushTimer: number | null = null

    const flushAssistant = () => {
      if (!pendingText) return
      assistantText += pendingText
      pendingText = ''
      useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
        content: assistantText,
      })
    }

    const syncSteps = () => {
      useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
        steps: assistantSteps,
      })
    }

    const updateAssistantStep = (stepId: string, patch: Partial<TaskStep>) => {
      assistantSteps = assistantSteps.map((s) => (s.id === stepId ? { ...s, ...patch } : s))
      syncSteps()
    }

    const startRunningStep = (title: string, extra?: Partial<TaskStep>) => {
      const t = new Date().toISOString()
      if (runningStepId) {
        updateStep(taskId, runningStepId, { status: 'completed', endTime: t })
        updateAssistantStep(runningStepId, { status: 'completed', endTime: t })
      }

      const step: TaskStep = {
        id: generateId(),
        title,
        status: 'running',
        startTime: t,
        ...extra,
      }
      runningStepId = step.id
      addStep(taskId, step)
      assistantSteps = [...assistantSteps, step]
      syncSteps()
    }

    startRunningStep('接收请求并开始生成…')

    void fetchSSE(
      '/study-materials/generate',
      { query: prompt },
      (data) => {
        const evt = data as StudyMaterialsAgentEvent
        const kind = typeof (evt as any)?.event === 'string' ? (evt as any).event : ''
        const payload = (evt as any)?.data

        if (kind === 'thinking') {
          const text = toText(payload?.content) || '思考中…'
          startRunningStep(text)
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 20 })
          return
        }

        if (kind === 'tool_call') {
          const name = toText(payload?.name) || 'tool'
          startRunningStep(`调用工具：${name}`, { toolName: name, input: payload?.arguments })
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 40 })
          return
        }

        if (kind === 'content') {
          const chunk = toText(payload?.content)
          if (chunk) {
            pendingText += chunk
            if (flushTimer == null) {
              flushTimer = window.setTimeout(() => {
                flushTimer = null
                flushAssistant()
              }, 60)
            }
          }
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 70 })
          return
        }

        if (kind === 'done') {
          done = true
          if (flushTimer != null) {
            window.clearTimeout(flushTimer)
            flushTimer = null
          }
          flushAssistant()

          const t = new Date().toISOString()
          if (runningStepId) {
            updateStep(taskId, runningStepId, { status: 'completed', endTime: t })
            updateAssistantStep(runningStepId, { status: 'completed', endTime: t })
          }

          const md = toText(payload?.material?.markdown)
          if (md) {
            assistantText = md
            useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
              content: md,
              steps: assistantSteps,
            })
          } else {
            useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
              content: assistantText,
              steps: assistantSteps,
            })
          }

          updateConversation(conversationId!, {
            title: toConversationTitle(prompt),
            updatedAt: t,
            status: 'completed',
            progress: 100,
          })

          completeTask(taskId)
          setIsGenerating(false)
          return
        }

        if (kind === 'error') {
          done = true
          const msg = toText(payload?.message) || '生成失败'
          setError(msg)
          failTask(taskId, msg)
          useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
            content: `出错：${msg}`,
            steps: assistantSteps,
          })
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), status: 'active' })
          setIsGenerating(false)
        }
      },
      (err) => {
        if (done) return
        const msg = err.message || '生成失败'
        setError(msg)
        failTask(taskId, msg)
        useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
          content: `出错：${msg}`,
          steps: assistantSteps,
        })
        setIsGenerating(false)
      },
      () => {
        if (!done) {
          completeTask(taskId)
          setIsGenerating(false)
        }
      }
    )
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* Top bar */}
      <div className="border-b border-border p-3 glass flex items-center justify-between">
        <div className="text-sm font-medium text-muted-foreground">
          自学资料生成 · Manus 时间轴
        </div>
        <Button variant="outline" size="sm" onClick={handleNewConversation} className="gap-2">
          <Plus className="h-4 w-4" />
          新建自学资料对话
        </Button>
      </div>

      {/* Messages */}
      {messages.length === 0 ? (
        <WelcomeScreen />
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-auto p-4">
          <div className="max-w-4xl mx-auto">
            <AnimatePresence initial={false}>
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </AnimatePresence>
          </div>
        </div>
      )}

      {/* Input */}
      <form onSubmit={handleSubmit} className="border-t border-border glass p-4">
        <div className="max-w-4xl mx-auto flex gap-3 items-end">
          <div className="flex-1">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="例如：函数单调性 / 二次函数最值 / 受力分析 / 化学平衡常数…（Enter 发送，Shift+Enter 换行）"
              className="min-h-[56px] max-h-40 resize-none"
              disabled={isGenerating}
            />
            {error && <div className="mt-2 text-sm text-destructive">出错：{error}</div>}
          </div>
          <Button type="submit" disabled={isGenerating || !input.trim()} className="gap-2">
            {isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            发送
          </Button>
        </div>
      </form>
    </div>
  )
}

