import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import 'katex/dist/katex.min.css'
import {
  Loader2,
  Plus,
  Send,
  Layers,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { TaskProgressHeader } from '@/components/task/TaskProgressHeader'
import { useSubjects } from '@/hooks/useSubjects'
import { useFormDraft } from '@/hooks/useFormDraft'
import { apiClient, resolveApiResourceUrl } from '@/api/client'
import { useAuthStore } from '@/stores/useAuthStore'
import { useConversationStore } from '@/stores/useConversationStore'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { appendCappedText, mergeAndSanitizeTaskStep, sanitizeTaskStep, sanitizeTaskSteps } from '@/lib/taskPayload'
import { cn, generateId } from '@/lib/utils'
import type { ConversationItem, TaskStep } from '@/types'
import * as tasksApi from '@/api/tasks'
import { DraggableDivider } from '@/features/lessonPlans/components/DraggableDivider'
import { MessageBubble } from '@/features/lessonPlans/components/MessageBubble'
import { SubAgentPanel } from '@/features/lessonPlans/components/SubAgentPanel'
import { WelcomeScreen } from '@/features/lessonPlans/components/WelcomeScreen'
import {
  extractDurationMinutesFromText,
  extractGradeFromText,
  extractSubjectFromText,
  extractTopicFromText,
  toConversationTitle,
  toText,
} from '@/features/lessonPlans/lib/promptParsing'
import type { SubAgentActivity } from '@/features/lessonPlans/types'

// ── Main page component ─────────────────────────────────────────────

function LessonPlansView() {
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const streamAbortRef = useRef<AbortController | null>(null)
  const userId = useAuthStore((s) => s.user?.id || '')
  const [searchParams, setSearchParams] = useSearchParams()
  const reuseTaskId = String(searchParams.get('reuse_task') || '').trim()

  const [input, setInput] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [activeUnifiedTaskId, setActiveUnifiedTaskId] = useState('')
  const activeUnifiedTaskIdRef = useRef<string>('')
  const [error, setError] = useState<string | null>(null)

  // Split pane: left panel width ratio (0.25 to 0.75)
  const [leftRatio, setLeftRatio] = useState(0.38)

  // SubAgent activities for the right panel
  const [subAgentActivities, setSubAgentActivities] = useState<SubAgentActivity[]>([])

  const { data: subjects } = useSubjects()

  const conversations = useConversationStore((state) => state.conversations)
  const currentConversationId = useConversationStore((state) => state.currentConversationIdByType.lesson_plan)
  const addConversation = useConversationStore((state) => state.addConversation)
  const setCurrentConversation = useConversationStore((state) => state.setCurrentConversation)
  const updateConversation = useConversationStore((state) => state.updateConversation)
  const setMessages = useConversationStore((state) => state.setMessages)
  const addMessage = useConversationStore((state) => state.addMessage)

  const savePlan = useLessonPlanStore((state) => state.savePlan)
  const { startTask, addStep, updateStep, completeTask, failTask } = useTaskStore()

  const activeConversationId = useMemo(() => {
    if (!currentConversationId) return null
    const current = conversations.find((c) => c.id === currentConversationId)
    return current?.type === 'lesson_plan' ? currentConversationId : null
  }, [conversations, currentConversationId])

  const draftKey = `draft:lesson-plans:v1:${userId || 'anon'}`
  const { clearDraft } = useFormDraft({
    storageKey: draftKey,
    enabled: !activeConversationId && !isGenerating,
    value: { input },
    shouldSave: (v: any) => Boolean(String(v?.input || '').trim()),
    onRestore: (data: any) => {
      setInput(String(data?.input || ''))
    },
  })

  useEffect(() => {
    if (!reuseTaskId) return
    let active = true
    const run = async () => {
      try {
        const task = await tasksApi.getTask(reuseTaskId)
        if (!active) return
        const req = (task as any)?.request
        if (!req || typeof req !== 'object' || Array.isArray(req)) return

        setCurrentConversation(null, 'lesson_plan')

        const subject = String((req as any).subject || '').trim()
        const grade = String((req as any).grade || '').trim()
        const topic = String((req as any).topic || '').trim()
        const duration = (req as any).duration_minutes
        const extra = String((req as any).additional_requirements || '').trim()

        const parts = [
          [subject, grade, topic ? `《${topic}》` : ''].filter(Boolean).join(' '),
          duration ? `${String(duration)}分钟` : '',
          '教案',
          extra,
        ].filter(Boolean)

        setInput(parts.join('\n'))
      } finally {
        const next = new URLSearchParams(searchParams)
        next.delete('reuse_task')
        setSearchParams(next, { replace: true })
      }
    }
    void run()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reuseTaskId])

  const messages = useConversationStore((state) =>
    state.getMessages(activeConversationId ?? '')
  )

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages.length])

  // Sidebar "new conversation" clears the current conversation selection but does not reset
  // page-local React state. Reset here so the UI is actually clean.
  useEffect(() => {
    if (activeConversationId) return
    if (streamAbortRef.current) {
      streamAbortRef.current.abort()
      streamAbortRef.current = null
    }
    setIsGenerating(false)
    setActiveUnifiedTaskId('')
    activeUnifiedTaskIdRef.current = ''
    setInput('')
    setError(null)
    setSubAgentActivities([])
  }, [activeConversationId])

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
    if (streamAbortRef.current) {
      streamAbortRef.current.abort()
      streamAbortRef.current = null
    }
    setIsGenerating(false)
    setActiveUnifiedTaskId('')
    activeUnifiedTaskIdRef.current = ''

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
    setError(null)
    setSubAgentActivities([])
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const prompt = input.trim()
    if (!prompt || isGenerating) return

    if (streamAbortRef.current) {
      streamAbortRef.current.abort()
      streamAbortRef.current = null
    }

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
    setError(null)
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

    let taskId = ''
    setIsGenerating(true)

    let done = false

    let assistantSteps: TaskStep[] = []
    let thinkingStepId: string | null = null
    let thinkingBuffer = ''

    // Track current subagent index for the right panel
    let currentSubAgentKP: string | null = null

    const syncSteps = () => {
      useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
        steps: assistantSteps,
      })
    }

    const addAssistantStep = (step: TaskStep) => {
      assistantSteps = sanitizeTaskSteps([...assistantSteps, sanitizeTaskStep(step)])
      syncSteps()
    }

    const patchAssistantStep = (stepId: string, patch: Partial<TaskStep>) => {
      assistantSteps = sanitizeTaskSteps(
        assistantSteps.map((s) => (s.id === stepId ? mergeAndSanitizeTaskStep(s, patch) : s))
      )
      syncSteps()
    }

    const controller = new AbortController()
    streamAbortRef.current = controller

    void apiClient
      .post(
        '/tasks/lesson-plans/generate',
        {
          subject: resolvedSubject,
          grade: resolvedGrade,
          topic: resolvedTopic,
          duration_minutes: resolvedDuration,
          objectives: resolvedObjectives.length > 0 ? resolvedObjectives : undefined,
          additional_requirements: resolvedAdditional || undefined,
        },
        { signal: controller.signal }
      )
      .then((res) => {
        if (streamAbortRef.current !== controller) return
        const unifiedTaskId = String((res.data as any)?.taskId || '').trim()
        if (!unifiedTaskId) throw new Error('missing_task_id')

        taskId = unifiedTaskId
        activeUnifiedTaskIdRef.current = unifiedTaskId
        setActiveUnifiedTaskId(unifiedTaskId)
        startTask(unifiedTaskId)

        tasksApi.streamTask(
          unifiedTaskId,
          0,
          (evt) => {
            if (streamAbortRef.current !== controller) return
            const kind = String(evt.type || '').trim()
            if (kind === 'ping' || kind === 'step') return

            const payload = evt.data

        if (kind === 'thinking') {
          const text = toText(payload?.content) || '思考中…'
          const t = new Date().toISOString()

          if (!thinkingStepId) {
            thinkingStepId = `thinking-${generateId()}`
            thinkingBuffer = ''
            const step: TaskStep = sanitizeTaskStep({
              id: thinkingStepId,
              title: '思考',
              status: 'running',
              startTime: t,
              toolName: 'thinking',
              output: '',
            })
            addAssistantStep(step)
            addStep(taskId, step)
          }

          thinkingBuffer = appendCappedText(thinkingBuffer, text)
          patchAssistantStep(thinkingStepId, { output: thinkingBuffer })
          updateStep(taskId, thinkingStepId, { output: thinkingBuffer })

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 15 })
          return
        }

        if (kind === 'tool_call') {
          const name = toText(payload?.name) || 'tool'

          // Close the current thinking step when the agent starts executing tools.
          if (thinkingStepId) {
            const tThinking = new Date().toISOString()
            patchAssistantStep(thinkingStepId, { status: 'completed', endTime: tThinking })
            updateStep(taskId, thinkingStepId, { status: 'completed', endTime: tThinking })
            thinkingStepId = null
            thinkingBuffer = ''
          }

          const stepId = toText((payload as any)?.step_id) || generateId()
          const stepTitle = toText((payload as any)?.title)
          const t = new Date().toISOString()

          const step: TaskStep = sanitizeTaskStep({
            id: stepId,
            title: stepTitle || `调用工具：${name}`,
            status: 'running',
            startTime: t,
            toolName: name,
            input: (payload as any)?.arguments,
          })

          if (!assistantSteps.some((s) => s.id === stepId)) {
            addAssistantStep(step)
            addStep(taskId, step)
          } else {
            patchAssistantStep(stepId, step)
            updateStep(taskId, stepId, step)
          }

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 35 })

          // If this is a subagent tool call, add step to the current subagent activity
          if (currentSubAgentKP) {
            setSubAgentActivities((prev) =>
              prev.map((a) =>
                a.knowledgePoint === currentSubAgentKP
                  ? {
                      ...a,
                      steps: sanitizeTaskSteps([
                        ...a.steps,
                        sanitizeTaskStep({
                          id: stepId,
                          title: stepTitle || `调用 ${name}`,
                          status: 'running' as const,
                          toolName: name,
                          startTime: t,
                        }),
                      ]),
                    }
                  : a
              )
            )
          }
          return
        }

        if (kind === 'tool_result') {
          const toolName = toText((payload as any)?.name) || ''
          const stepId = toText((payload as any)?.step_id)
          if (!stepId) return

          const success = (payload as any)?.success === true
          const out = (payload as any)?.output
          const err = toText((payload as any)?.error)
          const t = new Date().toISOString()

          patchAssistantStep(stepId, {
            status: success ? 'completed' : 'failed',
            endTime: t,
            output: out,
            error: err || undefined,
            toolName: toolName || undefined,
          })
          updateStep(taskId, stepId, {
            status: success ? 'completed' : 'failed',
            endTime: t,
            output: out,
            error: err || undefined,
          })

          // If split/review produced knowledge points, initialize the right panel list.
          if (
            (toolName === 'split_knowledge_points' || toolName === 'review_knowledge_points') &&
            out &&
            typeof out === 'object'
          ) {
            const kps = Array.isArray((out as any).knowledge_points)
              ? ((out as any).knowledge_points as string[])
              : []
            if (kps.length > 0) {
              setSubAgentActivities(
                kps.map((kp) => ({
                  knowledgePoint: kp,
                  status: 'pending' as const,
                  steps: [],
                }))
              )
            }
          }

          // Complete the running step in current subagent
          if (currentSubAgentKP) {
            setSubAgentActivities((prev) =>
              prev.map((a) =>
                a.knowledgePoint === currentSubAgentKP
                  ? {
                      ...a,
                      status: !success ? ('failed' as const) : a.status,
                      steps: sanitizeTaskSteps(
                        a.steps.map((s) =>
                          s.id === stepId
                            ? mergeAndSanitizeTaskStep(s, {
                                status: success ? ('completed' as const) : ('failed' as const),
                                endTime: t,
                              })
                            : s
                        )
                      ),
                    }
                  : a
              )
            )
          }

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 55 })
          return
        }

        if (kind === 'subagent_start') {
          const kp = toText(payload?.knowledge_point)
          currentSubAgentKP = kp || null

          // Mark this activity as running
          setSubAgentActivities((prev) =>
            prev.map((a) =>
              a.knowledgePoint === kp ? { ...a, status: 'running' as const } : a
            )
          )

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 45 })
          return
        }

        if (kind === 'subagent_end') {
          const kp = toText(payload?.knowledge_point)
          currentSubAgentKP = null

          // Mark this activity as completed
          setSubAgentActivities((prev) =>
            prev.map((a) =>
              a.knowledgePoint === kp
                ? {
                    ...a,
                    status:
                      a.status === 'failed' || a.steps.some((s) => s.status === 'failed')
                        ? ('failed' as const)
                        : ('completed' as const),
                    steps: sanitizeTaskSteps(
                      a.steps.map((s) =>
                        s.status === 'running'
                          ? mergeAndSanitizeTaskStep(s, {
                              status: 'completed' as const,
                              endTime: new Date().toISOString(),
                            })
                          : s
                      )
                    ),
                  }
                : a
            )
          )
          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), progress: 70 })
          return
        }

        if (kind === 'done') {
          done = true

          const t = new Date().toISOString()
          if (thinkingStepId) {
            patchAssistantStep(thinkingStepId, { status: 'completed', endTime: t })
            updateStep(taskId, thinkingStepId, { status: 'completed', endTime: t })
          }

          const material = (payload as any)?.material as any
          const title = toText(material?.title) || resolvedTopic || '教案'
          const durationMinutes =
            typeof material?.duration_minutes === 'number' ? material.duration_minutes : resolvedDuration
          const mdUrl = toText(material?.md_url)
          const pdfUrl = toText(material?.pdf_url)
          const mdFilename = toText(material?.md_filename)
          const pdfFilename = toText(material?.pdf_filename)
          const mdHref = mdUrl ? resolveApiResourceUrl(mdUrl) : ''
          const pdfHref = pdfUrl ? resolveApiResourceUrl(pdfUrl) : ''

          const lines: string[] = [
            '已生成教案，可下载：',
            '',
            mdHref ? `- Markdown： [下载 Markdown](${mdHref})` : '- Markdown： （生成失败或未导出）',
            pdfHref ? `- PDF： [下载 PDF](${pdfHref})` : '- PDF： （生成失败或未编译）',
          ]
          const content = lines.join('\n')

          savePlan({
            id: conversationId!,
            title,
            subject: resolvedSubject,
            grade: resolvedGrade,
            objectives: resolvedObjectives,
            duration: durationMinutes,
            createdAt: t,
            mdUrl: mdUrl || undefined,
            pdfUrl: pdfUrl || undefined,
            mdFilename: mdFilename || undefined,
            pdfFilename: pdfFilename || undefined,
          })

          useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
            content,
            attachment: { type: 'lesson_plan', lessonPlanId: conversationId! },
            steps: assistantSteps,
          })

          updateConversation(conversationId!, {
            title,
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
          const msg = toText((payload as any)?.message) || toText((payload as any)?.error) || '生成失败'
          setError(msg)
          if (taskId) failTask(taskId, msg)

          if (thinkingStepId) {
            const t = new Date().toISOString()
            patchAssistantStep(thinkingStepId, { status: 'failed', endTime: t, error: msg })
          }

          useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
            content: `出错：${msg}`,
            steps: assistantSteps,
          })

          updateConversation(conversationId!, { updatedAt: new Date().toISOString(), status: 'active' })
          setIsGenerating(false)
          return
        }
          },
          (err: Error) => {
            if (streamAbortRef.current !== controller) return
            streamAbortRef.current = null
            if (done) return
            done = true
            const msg = err.message || '生成失败'
            setError(msg)
            if (taskId) failTask(taskId, msg)

            if (thinkingStepId) {
              const t = new Date().toISOString()
              patchAssistantStep(thinkingStepId, { status: 'failed', endTime: t, error: msg })
            }

            useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
              content: `出错：${msg}`,
              steps: assistantSteps,
            })
            updateConversation(conversationId!, { updatedAt: new Date().toISOString(), status: 'active' })
            setIsGenerating(false)
          },
          () => {
            if (streamAbortRef.current !== controller) return
            streamAbortRef.current = null
            if (!done) {
              if (taskId) completeTask(taskId)
              setIsGenerating(false)
            }
          },
          { signal: controller.signal }
        )
      })
      .catch((err: any) => {
        if (streamAbortRef.current !== controller) return
        streamAbortRef.current = null
        if (done) return
        done = true

        const msg = typeof err?.message === 'string' ? err.message : '生成失败'
        setError(msg)

        useConversationStore.getState().updateMessage(conversationId!, assistantMessageId, {
          content: `出错：${msg}`,
          steps: assistantSteps,
        })
        updateConversation(conversationId!, { updatedAt: new Date().toISOString(), status: 'active' })
        setIsGenerating(false)
      })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const showSplitPane = isGenerating || subAgentActivities.length > 0

  return (
    <div ref={containerRef} className="h-full flex flex-col relative">
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
                {!!activeUnifiedTaskId && (
                  <div className="sticky top-0 z-10 pb-3 bg-background/80 backdrop-blur-sm">
                    <TaskProgressHeader taskId={activeUnifiedTaskId} compact />
                  </div>
                )}
                <AnimatePresence mode="popLayout">
                  {messages.map((m) => (
                    <MessageBubble key={m.id} message={m} />
                  ))}
                </AnimatePresence>

                {isGenerating && messages[messages.length - 1]?.content === '' && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex gap-3 mb-4"
                  >
                    <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                      <Loader2 className="h-3 w-3 animate-spin text-primary" />
                    </div>
                    <div className="text-sm text-muted-foreground pt-0.5">
                      正在生成教案...
                    </div>
                  </motion.div>
                )}

                {error && (
                  <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 mb-4 text-sm text-destructive flex items-center gap-2">
                    <div className="h-2 w-2 rounded-full bg-destructive shrink-0" />
                    {error}
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
              className="flex flex-col overflow-hidden border-l border-border bg-muted/20"
              style={{ width: `${(1 - leftRatio) * 100}%` }}
            >
              <div className="px-4 py-3 border-b border-border bg-background/50 backdrop-blur-sm">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Layers className="h-4 w-4 text-primary" />
                  SubAgent 工作区
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  逐知识点深入研究，为教案提供素材
                </div>
              </div>
              <SubAgentPanel activities={subAgentActivities} />
            </div>
          )}
        </div>
      )}

      {/* ── Composer ── */}
      <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-background via-background to-transparent pt-10"
        style={showSplitPane ? { width: `${leftRatio * 100}%` } : undefined}
      >
        <div className="max-w-3xl mx-auto">
          <form onSubmit={handleSubmit} className="relative group">
            <div className="relative flex items-end gap-2 p-2 rounded-2xl border bg-background shadow-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 transition-all">
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

              <Textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="例如：帮我写一份高中数学高二《函数单调性与导数应用》45分钟教案，偏互动式..."
                className="min-h-[44px] max-h-[200px] w-full resize-none border-0 bg-transparent py-2.5 px-0 focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50"
                disabled={isGenerating}
                rows={1}
                style={{ height: 'auto', overflow: 'hidden' }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement
                  target.style.height = 'auto'
                  target.style.height = `${Math.min(target.scrollHeight, 200)}px`
                }}
              />

              <Button
                type="submit"
                size="icon"
                className={cn(
                  'h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all',
                  input.trim() ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                )}
                disabled={!input.trim() || isGenerating}
              >
                {isGenerating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </form>

          <div className="text-center mt-2 text-[10px] text-muted-foreground/50">
            教案生成基于 AI 模型，仅供参考。
          </div>
        </div>
      </div>
    </div>
  )
}

export default LessonPlansView
