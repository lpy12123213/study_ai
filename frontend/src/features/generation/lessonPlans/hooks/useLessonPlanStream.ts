import { useCallback, useRef, useState } from 'react'
import { LONG_TASK_CREATE_TIMEOUT_MS, apiClient, resolveApiResourceUrl } from '@/api/client'
import * as tasksApi from '@/api/tasks'
import { useConversationStore } from '@/stores/useConversationStore'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { useTaskStore } from '@/stores/useTaskStore'
import {
  appendCappedText,
  mergeAndSanitizeTaskStep,
  sanitizeTaskStep,
  sanitizeTaskSteps,
} from '@/lib/taskPayload'
import { isRecord, readString } from '@/lib/record'
import { generateId } from '@/lib/utils'
import { toText } from '@/features/generation/lessonPlans/lib/promptParsing'
import type { TaskStep } from '@/types'
import type { SubAgentActivity } from '@/features/generation/lessonPlans/types'

function eventDataRecord(data: unknown): Record<string, unknown> {
  return isRecord(data) ? data : {}
}

export type LessonPlanGenerateRequest = {
  conversationId: string
  assistantMessageId: string
  resolvedSubject: string
  resolvedGrade: string
  resolvedTopic: string
  resolvedDuration: number
  resolvedObjectives: string[]
  resolvedAdditional: string
}

export type LessonPlanStreamHook = {
  /** Currently running task id (unified `/api/tasks` id), if any. */
  activeUnifiedTaskId: string
  /** Whether a request is in flight or events are still streaming. */
  isGenerating: boolean
  /** Latest user-visible error, or null. */
  error: string | null
  /** Reset error to null. */
  clearError: () => void
  /** Cancel any active stream. Safe to call multiple times. */
  abort: () => void
  /** Start a new lesson-plan generation task. */
  start: (request: LessonPlanGenerateRequest) => void
  /** Reset all controller state (used when the user opens a new conversation). */
  reset: () => void
}

/**
 * Encapsulates the SSE-driven lesson-plan generation flow:
 * - POST `/tasks/lesson-plans/generate` to create a task
 * - Subscribe to `/tasks/{id}/stream` for `thinking` / `tool_call` / `tool_result`
 *   / `subagent_*` / `done` / `error` events
 * - Maintain `assistantSteps`, `thinking` step, `subAgentActivities`,
 *   `conversation.progress`, and the final attached lesson-plan record
 *
 * The page component just wires the controller to its own draft/messages state.
 */
export function useLessonPlanStream(opts: {
  setSubAgentActivities: React.Dispatch<React.SetStateAction<SubAgentActivity[]>>
}): LessonPlanStreamHook {
  const { setSubAgentActivities } = opts

  const streamAbortRef = useRef<AbortController | null>(null)
  const activeUnifiedTaskIdRef = useRef<string>('')

  const [activeUnifiedTaskId, setActiveUnifiedTaskId] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { startTask, addStep, updateStep, completeTask, failTask } = useTaskStore()

  const abort = useCallback(() => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort()
      streamAbortRef.current = null
    }
  }, [])

  const reset = useCallback(() => {
    abort()
    setIsGenerating(false)
    setActiveUnifiedTaskId('')
    activeUnifiedTaskIdRef.current = ''
    setError(null)
  }, [abort])

  const start = useCallback(
    (request: LessonPlanGenerateRequest) => {
      const {
        conversationId,
        assistantMessageId,
        resolvedSubject,
        resolvedGrade,
        resolvedTopic,
        resolvedDuration,
        resolvedObjectives,
        resolvedAdditional,
      } = request

      abort()
      setError(null)
      setIsGenerating(true)

      let taskId = ''
      let done = false
      let assistantSteps: TaskStep[] = []
      let thinkingStepId: string | null = null
      let thinkingBuffer = ''
      let currentSubAgentKP: string | null = null

      const syncSteps = () => {
        useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
          steps: assistantSteps,
        })
      }

      const addAssistantStep = (step: TaskStep) => {
        assistantSteps = sanitizeTaskSteps([...assistantSteps, sanitizeTaskStep(step)])
        syncSteps()
      }

      const patchAssistantStep = (stepId: string, patch: Partial<TaskStep>) => {
        assistantSteps = sanitizeTaskSteps(
          assistantSteps.map((s) => (s.id === stepId ? mergeAndSanitizeTaskStep(s, patch) : s)),
        )
        syncSteps()
      }

      const updateConversation = (
        patch: Parameters<ReturnType<typeof useConversationStore.getState>['updateConversation']>[1],
      ) => {
        useConversationStore.getState().updateConversation(conversationId, patch)
      }

      const finalizeError = (msg: string) => {
        setError(msg)
        if (taskId) failTask(taskId, msg)

        if (thinkingStepId) {
          const t = new Date().toISOString()
          patchAssistantStep(thinkingStepId, { status: 'failed', endTime: t, error: msg })
        }

        useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
          content: `出错：${msg}`,
          steps: assistantSteps,
        })
        updateConversation({ updatedAt: new Date().toISOString(), status: 'active' })
        setIsGenerating(false)
      }

      const controller = new AbortController()
      streamAbortRef.current = controller

      const handleEvent = (kind: string, payload: Record<string, unknown>) => {
        if (kind === 'thinking') {
          const text = toText(payload.content) || '思考中…'
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

          updateConversation({ updatedAt: new Date().toISOString(), progress: 15 })
          return
        }

        if (kind === 'tool_call') {
          const name = toText(payload.name) || 'tool'

          // Close the current thinking step when the agent starts executing tools.
          if (thinkingStepId) {
            const tThinking = new Date().toISOString()
            patchAssistantStep(thinkingStepId, { status: 'completed', endTime: tThinking })
            updateStep(taskId, thinkingStepId, { status: 'completed', endTime: tThinking })
            thinkingStepId = null
            thinkingBuffer = ''
          }

          const stepId = toText(payload.step_id) || generateId()
          const stepTitle = toText(payload.title)
          const t = new Date().toISOString()

          const step: TaskStep = sanitizeTaskStep({
            id: stepId,
            title: stepTitle || `调用工具：${name}`,
            status: 'running',
            startTime: t,
            toolName: name,
            input: payload.arguments,
          })

          if (!assistantSteps.some((s) => s.id === stepId)) {
            addAssistantStep(step)
            addStep(taskId, step)
          } else {
            patchAssistantStep(stepId, step)
            updateStep(taskId, stepId, step)
          }

          updateConversation({ updatedAt: new Date().toISOString(), progress: 35 })

          if (currentSubAgentKP) {
            const kp = currentSubAgentKP
            setSubAgentActivities((prev) =>
              prev.map((a) =>
                a.knowledgePoint === kp
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
                  : a,
              ),
            )
          }
          return
        }

        if (kind === 'tool_result') {
          const toolName = toText(payload.name) || ''
          const stepId = toText(payload.step_id)
          if (!stepId) return

          const success = payload.success === true
          const out = payload.output
          const err = toText(payload.error)
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
            isRecord(out)
          ) {
            const kpRaw = out.knowledge_points
            const kps = Array.isArray(kpRaw) ? kpRaw.filter((x): x is string => typeof x === 'string') : []
            if (kps.length > 0) {
              setSubAgentActivities(
                kps.map((kp) => ({
                  knowledgePoint: kp,
                  status: 'pending' as const,
                  steps: [],
                })),
              )
            }
          }

          if (currentSubAgentKP) {
            const kp = currentSubAgentKP
            setSubAgentActivities((prev) =>
              prev.map((a) =>
                a.knowledgePoint === kp
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
                            : s,
                        ),
                      ),
                    }
                  : a,
              ),
            )
          }

          updateConversation({ updatedAt: new Date().toISOString(), progress: 55 })
          return
        }

        if (kind === 'subagent_start') {
          const kp = toText(payload.knowledge_point)
          currentSubAgentKP = kp || null

          setSubAgentActivities((prev) =>
            prev.map((a) => (a.knowledgePoint === kp ? { ...a, status: 'running' as const } : a)),
          )

          updateConversation({ updatedAt: new Date().toISOString(), progress: 45 })
          return
        }

        if (kind === 'subagent_end') {
          const kp = toText(payload.knowledge_point)
          currentSubAgentKP = null

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
                          : s,
                      ),
                    ),
                  }
                : a,
            ),
          )
          updateConversation({ updatedAt: new Date().toISOString(), progress: 70 })
          return
        }

        if (kind === 'done') {
          done = true

          const t = new Date().toISOString()
          if (thinkingStepId) {
            patchAssistantStep(thinkingStepId, { status: 'completed', endTime: t })
            updateStep(taskId, thinkingStepId, { status: 'completed', endTime: t })
          }

          const material = isRecord(payload.material) ? payload.material : {}
          const title = toText(material.title) || resolvedTopic || '教案'
          const durationMinutes =
            typeof material.duration_minutes === 'number' ? material.duration_minutes : resolvedDuration
          const mdUrl = toText(material.md_url)
          const pdfUrl = toText(material.pdf_url)
          const mdFilename = toText(material.md_filename)
          const pdfFilename = toText(material.pdf_filename)
          const mdHref = mdUrl ? resolveApiResourceUrl(mdUrl) : ''
          const pdfHref = pdfUrl ? resolveApiResourceUrl(pdfUrl) : ''

          const lines: string[] = [
            '已生成教案，可下载：',
            '',
            mdHref ? `- 可编辑文档： [下载可编辑文档](${mdHref})` : '- 可编辑文档： （生成失败或未导出）',
            pdfHref ? `- PDF： [下载 PDF](${pdfHref})` : '- PDF： （生成失败或未编译）',
          ]
          const content = lines.join('\n')

          useLessonPlanStore.getState().savePlan({
            id: conversationId,
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

          useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
            content,
            attachment: { type: 'lesson_plan', lessonPlanId: conversationId },
            steps: assistantSteps,
          })

          updateConversation({
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
          const msg = toText(payload.message) || toText(payload.error) || '生成失败'
          finalizeError(msg)
          return
        }
      }

      // Voice the absence of an unused symbol warning.
      void resolvedAdditional

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
          { signal: controller.signal, timeout: LONG_TASK_CREATE_TIMEOUT_MS },
        )
        .then((res) => {
          if (streamAbortRef.current !== controller) return
          const unifiedTaskId = readString(res.data, 'taskId').trim()
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
              const payload = eventDataRecord(evt.data)
              handleEvent(kind, payload)
            },
            (err: Error) => {
              if (streamAbortRef.current !== controller) return
              streamAbortRef.current = null
              if (done) return
              done = true
              finalizeError(err.message || '生成失败')
            },
            () => {
              if (streamAbortRef.current !== controller) return
              streamAbortRef.current = null
              if (!done) {
                if (taskId) completeTask(taskId)
                setIsGenerating(false)
              }
            },
            { signal: controller.signal },
          )
        })
        .catch((err: unknown) => {
          if (streamAbortRef.current !== controller) return
          streamAbortRef.current = null
          if (done) return
          done = true

          const msg = err instanceof Error ? err.message : readString(err, 'message') || '生成失败'
          setError(msg)

          useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
            content: `出错：${msg}`,
            steps: assistantSteps,
          })
          updateConversation({ updatedAt: new Date().toISOString(), status: 'active' })
          setIsGenerating(false)
        })
    },
    [abort, addStep, completeTask, failTask, setSubAgentActivities, startTask, updateStep],
  )

  return {
    activeUnifiedTaskId,
    isGenerating,
    error,
    clearError: () => setError(null),
    abort,
    start,
    reset,
  }
}
