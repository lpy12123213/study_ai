import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import 'katex/dist/katex.min.css'
import { Loader2, Plus, Send, Layers, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RichTextarea } from '@/components/shared/RichTextarea'
import { TaskProgressHeader } from '@/components/task/TaskProgressHeader'
import { useSubjects } from '@/hooks/useSubjects'
import { useFormDraft } from '@/hooks/useFormDraft'
import { useVirtualMessages } from '@/hooks/useVirtualMessages'
import { useAuthStore } from '@/stores/useAuthStore'
import { useConversationStore } from '@/stores/useConversationStore'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { readString } from '@/lib/record'
import { cn, generateId } from '@/lib/utils'
import type { ConversationItem } from '@/types'
import { DraggableDivider } from '@/features/generation/lessonPlans/components/DraggableDivider'
import { MessageBubble } from '@/features/generation/lessonPlans/components/MessageBubble'
import { SubAgentPanel } from '@/features/generation/lessonPlans/components/SubAgentPanel'
import { WelcomeScreen } from '@/features/generation/lessonPlans/components/WelcomeScreen'
import {
  extractDurationMinutesFromText,
  extractGradeFromText,
  extractSubjectFromText,
  extractTopicFromText,
  toConversationTitle,
} from '@/features/generation/lessonPlans/lib/promptParsing'
import { useLessonPlanReuseTask } from '@/features/generation/lessonPlans/hooks/useLessonPlanReuseTask'
import { useLessonPlanStream } from '@/features/generation/lessonPlans/hooks/useLessonPlanStream'
import type { SubAgentActivity } from '@/features/generation/lessonPlans/types'

function LessonPlansView() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const userId = useAuthStore((s) => s.user?.id || '')
  const [searchParams, setSearchParams] = useSearchParams()
  const reuseTaskId = String(searchParams.get('reuse_task') || '').trim()

  const [input, setInput] = useState('')
  const [leftRatio, setLeftRatio] = useState(0.38)
  const [subAgentActivities, setSubAgentActivities] = useState<SubAgentActivity[]>([])

  const { data: subjects } = useSubjects()

  const conversations = useConversationStore((state) => state.conversations)
  const currentConversationId = useConversationStore((state) => state.currentConversationIdByType.lesson_plan)
  const addConversation = useConversationStore((state) => state.addConversation)
  const setCurrentConversation = useConversationStore((state) => state.setCurrentConversation)
  const updateConversation = useConversationStore((state) => state.updateConversation)
  const setMessages = useConversationStore((state) => state.setMessages)
  const addMessage = useConversationStore((state) => state.addMessage)

  const stream = useLessonPlanStream({ setSubAgentActivities })

  const activeConversationId = useMemo(() => {
    if (!currentConversationId) return null
    const current = conversations.find((c) => c.id === currentConversationId)
    return current?.type === 'lesson_plan' ? currentConversationId : null
  }, [conversations, currentConversationId])

  const draftKey = `draft:lesson-plans:v1:${userId || 'anon'}`
  const { clearDraft } = useFormDraft<{ input: string }>({
    storageKey: draftKey,
    enabled: !activeConversationId && !stream.isGenerating,
    value: { input },
    shouldSave: (v) => Boolean(String(v.input || '').trim()),
    onRestore: (raw) => {
      const data: unknown = raw
      setInput(readString(data, 'input'))
    },
  })

  useLessonPlanReuseTask({
    reuseTaskId,
    setInput,
    onConsumed: () => {
      const next = new URLSearchParams(searchParams)
      next.delete('reuse_task')
      setSearchParams(next, { replace: true })
    },
  })

  const messages = useConversationStore((state) => state.getMessages(activeConversationId ?? ''))

  const shouldVirtualize = messages.length >= 500
  const virtual = useVirtualMessages({
    enabled: shouldVirtualize,
    messages,
    containerRef: scrollRef,
    estimatePx: 220,
    overscan: 12,
  })

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages.length])

  // Sidebar "new conversation" clears the current conversation selection but does not reset
  // page-local React state. Reset here so the UI is actually clean.
  useEffect(() => {
    if (activeConversationId) return
    stream.reset()
    setInput('')
    setSubAgentActivities([])
  }, [activeConversationId, stream.reset])

  const handleDrag = useCallback((deltaX: number) => {
    if (!containerRef.current) return
    const totalWidth = containerRef.current.offsetWidth
    if (totalWidth <= 0) return
    setLeftRatio((prev) => {
      const next = prev + deltaX / totalWidth
      return Math.max(0.2, Math.min(0.65, next))
    })
  }, [])

  const handleNewConversation = () => {
    stream.reset()

    const id = generateId()
    const now = new Date().toISOString()
    const item: ConversationItem = {
      id,
      title: '新教案',
      type: 'lesson_plan',
      createdAt: now,
      updatedAt: now,
      status: 'active',
      resumable: false,
    }
    addConversation(item)
    setCurrentConversation(id, 'lesson_plan')
    setMessages(id, [])
    setInput('')
    setSubAgentActivities([])
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const prompt = input.trim()
    if (!prompt || stream.isGenerating) return

    stream.abort()

    const now = new Date().toISOString()

    let conversationId = activeConversationId
    if (!conversationId) {
      const inferredGrade = extractGradeFromText(prompt)
      const inferredSubject = extractSubjectFromText(prompt, subjects, inferredGrade)
      const inferredTopic = extractTopicFromText(prompt, inferredSubject, inferredGrade)

      conversationId = generateId()
      const conversation: ConversationItem = {
        id: conversationId,
        title: toConversationTitle(inferredTopic || prompt),
        type: 'lesson_plan',
        createdAt: now,
        updatedAt: now,
        status: 'active',
        resumable: false,
        progress: 0,
      }
      addConversation(conversation)
      setCurrentConversation(conversationId, 'lesson_plan')
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
    stream.clearError()
    setSubAgentActivities([])

    const existingPlan = useLessonPlanStore.getState().getPlan(conversationId)

    const inferredGrade = extractGradeFromText(prompt)
    const resolvedGrade = (inferredGrade ?? existingPlan?.grade ?? '').trim()
    const inferredSubject = extractSubjectFromText(prompt, subjects, resolvedGrade || existingPlan?.grade || null)
    const resolvedSubject = (inferredSubject ?? existingPlan?.subject ?? '').trim()
    const inferredTopic = extractTopicFromText(prompt, resolvedSubject || null, resolvedGrade || null)
    const resolvedTopic = (inferredTopic || existingPlan?.title || '').trim()
    const resolvedDuration = extractDurationMinutesFromText(prompt) ?? existingPlan?.duration ?? 45
    const resolvedObjectives = existingPlan?.objectives ?? []
    const resolvedAdditional = prompt

    const missing: string[] = []
    if (!resolvedSubject) missing.push('学科')
    if (!resolvedGrade) missing.push('年级')
    if (!resolvedTopic) missing.push('课题')

    if (missing.length > 0) {
      addMessage(conversationId, {
        id: generateId(),
        role: 'assistant',
        createdAt: now,
        content:
          `为了生成教案，我还缺少：${missing.join('、')}。\n\n` +
          `请在消息里包含这些信息，例如：\n` +
          `"高中数学 高二 《函数单调性与导数应用》 45分钟 教案（互动式/含分层练习）"。`,
      })
      return
    }

    clearDraft()

    const titleCandidate = toConversationTitle(resolvedTopic)
    const current = conversations.find((c) => c.id === conversationId)
    if (!current || current.title.startsWith('新教案')) {
      updateConversation(conversationId, { title: titleCandidate, updatedAt: now })
    }

    const assistantMessageId = generateId()
    addMessage(conversationId, {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      createdAt: now,
      steps: [],
    })

    stream.start({
      conversationId,
      assistantMessageId,
      resolvedSubject,
      resolvedGrade,
      resolvedTopic,
      resolvedDuration,
      resolvedObjectives,
      resolvedAdditional,
    })
  }

  const showSplitPane = stream.isGenerating || subAgentActivities.length > 0
  const completedSubAgents = subAgentActivities.filter((activity) => activity.status === 'completed').length
  const runningSubAgents = subAgentActivities.filter((activity) => activity.status === 'running').length
  const lessonStats = [
    { label: '对话轮次', value: `${messages.length}` },
    { label: '知识点编队', value: `${completedSubAgents}/${subAgentActivities.length || 0}` },
    { label: '生成状态', value: stream.isGenerating ? '编排中' : stream.activeUnifiedTaskId ? '可追踪' : '待命' },
    { label: '研究中', value: runningSubAgents > 0 ? `${runningSubAgents} 个` : '无' },
  ]

  return (
    <div ref={containerRef} className="aurora-lesson-screen h-full flex flex-col relative">
      {/* Messages area (or welcome) */}
      {messages.length === 0 && !showSplitPane ? (
        <WelcomeScreen onExampleClick={(text) => setInput(text)} />
      ) : (
        <div className="flex-1 flex overflow-hidden">
          {/* ── Left column: Main agent (chat + steps) ── */}
          <div
            className="flex flex-col overflow-hidden"
            style={{ width: showSplitPane ? `${leftRatio * 100}%` : '100%' }}
          >
            <div ref={scrollRef} className="flex-1 overflow-auto p-4 pb-32">
              <div className="py-6">
                <section className="aurora-lesson-ops mb-5">
                  <div>
                    <div className="aurora-kicker">
                      <Sparkles className="h-3.5 w-3.5" />
                      Lesson Design Console
                    </div>
                    <h1 className="mt-3 text-2xl font-semibold tracking-tight">备课编排控制台</h1>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                      根据学科、年级、课题和课时自动拆解教学目标、活动流程、练习与板书结构，并用 SubAgent 补足知识点素材。
                    </p>
                  </div>
                  <div className="aurora-lesson-stat-grid">
                    {lessonStats.map((item) => (
                      <div key={item.label} className="aurora-lesson-stat">
                        <span>{item.label}</span>
                        <strong>{item.value}</strong>
                      </div>
                    ))}
                  </div>
                </section>
                {!!stream.activeUnifiedTaskId && (
                  <div className="aurora-lesson-sticky sticky top-0 z-10 pb-3">
                    <TaskProgressHeader taskId={stream.activeUnifiedTaskId} compact />
                  </div>
                )}
                {shouldVirtualize ? (
                  <div ref={virtual.listRef} className="relative" style={{ height: virtual.totalHeight }}>
                    {messages.slice(virtual.range.start, virtual.range.end).map((m, i) => {
                      const index = virtual.range.start + i
                      const mid = String(m.id)
                      const top = virtual.offsets[index] ?? 0
                      return (
                        <div
                          key={m.id}
                          ref={virtual.getMeasureRef(mid)}
                          className="absolute left-0 right-0 flow-root"
                          style={{ transform: `translateY(${top}px)` }}
                        >
                          <MessageBubble message={m} disableMotion={true} />
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <AnimatePresence mode="popLayout">
                    {messages.map((m) => (
                      <MessageBubble key={m.id} message={m} disableMotion={false} />
                    ))}
                  </AnimatePresence>
                )}

                {stream.isGenerating && messages[messages.length - 1]?.content === '' && (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="aurora-lesson-streaming flex gap-3 mb-4">
                    <div className="aurora-lesson-mark h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                      <Loader2 className="h-3 w-3 animate-spin text-primary" />
                    </div>
                    <div className="text-sm text-muted-foreground pt-0.5">正在生成教案...</div>
                  </motion.div>
                )}

                {stream.error && (
                  <div className="aurora-lesson-error rounded-lg p-4 mb-4 text-sm text-destructive flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-destructive shrink-0" />
                    {stream.error}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* ── Draggable divider ── */}
          {showSplitPane && <DraggableDivider onDrag={handleDrag} />}

          {/* ── Right column: SubAgent panel ── */}
          {showSplitPane && (
            <div
              className="aurora-lesson-sidecar flex flex-col overflow-hidden"
              style={{ width: `${(1 - leftRatio) * 100}%` }}
            >
              <div className="px-4 py-3 border-b border-border/70 bg-background/50 backdrop-blur-sm">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Layers className="h-4 w-4 text-primary" />
                  SubAgent 工作区
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">逐知识点深入研究，为教案提供素材</div>
              </div>
              <SubAgentPanel activities={subAgentActivities} />
            </div>
          )}
        </div>
      )}

      {/* ── Composer ── */}
      <div
        className="aurora-lesson-composer-shell absolute bottom-0 left-0 right-0 p-4 pt-10"
        style={showSplitPane ? { width: `${leftRatio * 100}%` } : undefined}
      >
        <div className="max-w-3xl mx-auto">
          <form onSubmit={handleSubmit} className="relative group">
            <div className="aurora-lesson-command relative flex items-end gap-2 p-2 rounded-2xl transition-all">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-xl text-muted-foreground hover:text-foreground shrink-0 mb-0.5"
                onClick={handleNewConversation}
                title="新建教案"
              >
                <Plus className="h-5 w-5" />
              </Button>

              <RichTextarea
                value={input}
                onChange={setInput}
                onSubmit={handleSubmit}
                submitOnEnter
                placeholder="例如：帮我写一份高中数学高二《函数单调性与导数应用》45分钟教案，偏互动式..."
                ariaLabel="教案生成要求"
                debounceMs={0}
                minHeight={44}
                maxHeight={200}
                className="min-h-[44px] w-full border-0 bg-transparent shadow-none focus-within:ring-0"
                editorClassName="px-0 py-2.5 placeholder:text-muted-foreground/50"
                disabled={stream.isGenerating}
              />

              <Button
                type="submit"
                size="icon"
                className={cn(
                  'h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all',
                  input.trim() ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
                )}
                disabled={!input.trim() || stream.isGenerating}
              >
                {stream.isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </Button>
            </div>
          </form>
          <div className="text-xs text-muted-foreground mt-2 text-center">
            按 Enter 发送，Shift+Enter 换行
          </div>
        </div>
      </div>
    </div>
  )
}

export default LessonPlansView
