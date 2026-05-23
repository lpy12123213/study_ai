import { useCallback, useRef } from 'react'
import { ApiError, fetchSSERequest, isApiError } from '@/api/client'
import { streamTaskWs } from '@/api/ws'
import { useConversationStore } from '@/stores/useConversationStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { appendCappedText, mergeAndSanitizeTaskStep, sanitizeTaskStep, sanitizeTaskSteps } from '@/lib/taskPayload'
import { normalizeSseEnvelope } from '@/lib/sse'
import { generateId } from '@/lib/utils'
import { formatStudyMaterialsError, normalizeKnowledgePoints, toText } from '@/features/generation/studyMaterials/utils'
import type { TaskStep } from '@/types'
import type { SubAgentActivity } from '@/features/generation/studyMaterials/types'

export type StudyMaterialsStreamRequest = { url: string; method: 'GET' | 'POST'; body?: unknown }

type StreamRecord = Record<string, unknown>

/**
 * Parse `/tasks/{taskId}/stream?after_seq=N` URL.
 * Returns null if the URL is not a unified-task stream URL.
 */
function parseTaskStreamUrl(url: string, method: string): { taskId: string; afterSeq: number } | null {
  if (method !== 'GET') return null
  const m = url.match(/^\/tasks\/([^/?#]+)\/stream(?:\?(.*))?$/)
  if (!m) return null
  const taskId = decodeURIComponent(m[1] || '')
  if (!taskId) return null
  let afterSeq = 0
  if (m[2]) {
    const params = new URLSearchParams(m[2])
    const raw = params.get('after_seq')
    if (raw) {
      const n = Number(raw)
      if (Number.isFinite(n) && n >= 0) afterSeq = Math.floor(n)
    }
  }
  return { taskId, afterSeq }
}

export type RunStudyMaterialsStreamOptions = {
  conversationId: string
  assistantMessageId: string
  request: StudyMaterialsStreamRequest
  localTaskId?: string
  initialTaskId?: string
  initialSeq?: number
  streamKey?: string
}

function toRecord(value: unknown): StreamRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as StreamRecord
}

function toTaskStepStatus(value: unknown, fallback: TaskStep['status']): TaskStep['status'] {
  const raw = toText(value).trim()
  return raw === 'pending' || raw === 'running' || raw === 'completed' || raw === 'failed' || raw === 'paused'
    ? raw
    : fallback
}

export function useStudyMaterialsStreamRunner(opts: {
  setIsGeneratingLocal: (next: boolean) => void
  setError: (next: unknown) => void
  setSubAgentActivities: React.Dispatch<React.SetStateAction<SubAgentActivity[]>>
  setActiveSubAgentTab: React.Dispatch<React.SetStateAction<string | null>>
}) {
  const { setIsGeneratingLocal, setError, setSubAgentActivities, setActiveSubAgentTab } = opts

  const streamAbortRef = useRef<AbortController | null>(null)
  const streamKeyRef = useRef<string | null>(null)

  const abortActiveStream = useCallback(() => {
    if (streamAbortRef.current) {
      streamAbortRef.current.abort()
      streamAbortRef.current = null
    }
    streamKeyRef.current = null
    setIsGeneratingLocal(false)
  }, [setIsGeneratingLocal])

  const runStudyMaterialsStream = useCallback(
    (runOpts: RunStudyMaterialsStreamOptions) => {
      const { conversationId, assistantMessageId, request, localTaskId } = runOpts
      const controller = new AbortController()
      const initialSeq = typeof runOpts.initialSeq === 'number' ? runOpts.initialSeq : 0

      // Cancel any existing stream before starting a new one.
      abortActiveStream()
      streamAbortRef.current = controller
      streamKeyRef.current = runOpts.streamKey || null

      let serverTaskId: string | null = (runOpts.initialTaskId || '').trim() || null
      let lastSeq = initialSeq

      const existing = useConversationStore
        .getState()
        .getMessages(conversationId)
        .find((m) => m.id === assistantMessageId)

      let assistantSteps: TaskStep[] = Array.isArray(existing?.steps) ? (existing?.steps as TaskStep[]) : []
      let assistantText = typeof existing?.content === 'string' ? existing!.content : ''
      let pendingText = ''
      let flushTimer: number | null = null
      let done = false

      // Streaming "thinking" panel (auto-expanded while running, auto-collapsed when finished).
      let thinkingStepId: string | null = null
      let thinkingStartTime: string | null = null
      let thinkingBuffer = ''

      let runningSubAgentKP: string | null = null
      const activeSubAgentKPs = new Set<string>()
      const subAgentStepKPById: Record<string, string> = {}
      const subThinkingStepIdByKP: Record<string, string> = {}
      const subThinkingStartTimeByKP: Record<string, string> = {}
      const subThinkingBufferByKP: Record<string, string> = {}

      const upsertSubAgentStep = (kp: string, step: TaskStep) => {
        const sanitizedStep = sanitizeTaskStep(step)
        setSubAgentActivities((prev) => {
          const exists = prev.some((a) => a.knowledgePoint === kp)
          const base = exists ? prev : [...prev, { knowledgePoint: kp, status: 'pending' as const, steps: [] }]
          return base.map((a) => {
            if (a.knowledgePoint !== kp) return a
            const hasStep = a.steps.some((s) => s.id === sanitizedStep.id)
            const steps = sanitizeTaskSteps(
              hasStep
                ? a.steps.map((s) => (s.id === sanitizedStep.id ? mergeAndSanitizeTaskStep(s, sanitizedStep) : s))
                : [...a.steps, sanitizedStep]
            )
            return { ...a, steps }
          })
        })
      }

      const patchSubAgentStep = (kp: string, stepId: string, patch: Partial<TaskStep>) => {
        setSubAgentActivities((prev) =>
          prev.map((a) => {
            if (a.knowledgePoint !== kp) return a
            const hasStep = a.steps.some((s) => s.id === stepId)
            if (!hasStep) {
              return {
                ...a,
                steps: sanitizeTaskSteps([
                  ...a.steps,
                  sanitizeTaskStep({
                    id: stepId,
                    title: patch.title || patch.toolName || '步骤',
                    status: patch.status || 'running',
                    startTime: patch.startTime,
                    endTime: patch.endTime,
                    toolName: patch.toolName,
                    input: patch.input,
                    output: patch.output,
                    error: patch.error,
                  }),
                ]),
              }
            }
            return {
              ...a,
              steps: sanitizeTaskSteps(a.steps.map((s) => (s.id === stepId ? mergeAndSanitizeTaskStep(s, patch) : s))),
            }
          })
        )
      }

      const updateSubAgentStatus = (kp: string) => {
        setSubAgentActivities((prev) =>
          prev.map((a) => {
            if (a.knowledgePoint !== kp) return a
            const hasRunning = a.steps.some((s) => s.status === 'running')
            const hasFailed = a.steps.some((s) => s.status === 'failed')
            const status: SubAgentActivity['status'] = hasRunning ? 'running' : hasFailed ? 'failed' : 'completed'
            return { ...a, status }
          })
        )
      }

      const initializeSubAgentActivities = (kps: string[]) => {
        if (kps.length === 0) return
        setSubAgentActivities((prev) => {
          const byKP = new Map(prev.map((a) => [a.knowledgePoint, a]))
          return kps.map((kp) => byKP.get(kp) || { knowledgePoint: kp, status: 'pending' as const, steps: [] })
        })
        setActiveSubAgentTab((prev) => prev || kps[0])
      }

      const getPayloadInput = (payload: StreamRecord) => payload.input ?? payload.arguments

      const getPayloadKnowledgePoint = (payload: StreamRecord, stepId?: string): string | null => {
        if (stepId && subAgentStepKPById[stepId]) return subAgentStepKPById[stepId]
        const input = getPayloadInput(payload)
        const kps = normalizeKnowledgePoints(toRecord(input).knowledge_points)
        if (kps.length === 1) return kps[0]
        const kp = toText(payload.knowledge_point || payload.knowledgePoint).trim()
        if (kp) return kp
        return null
      }

      const getSoleActiveSubAgent = (): string | null => {
        if (activeSubAgentKPs.size !== 1) return null
        return Array.from(activeSubAgentKPs)[0] || null
      }

      const flushAssistant = () => {
        if (flushTimer) {
          window.clearTimeout(flushTimer)
          flushTimer = null
        }

        const nextText = assistantText + pendingText
        if (!pendingText) return
        assistantText = nextText
        pendingText = ''

        useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
          content: assistantText,
          steps: assistantSteps,
        })
      }

      const scheduleFlush = () => {
        if (flushTimer) return
        flushTimer = window.setTimeout(() => flushAssistant(), 80)
      }

      const upsertStep = (step: TaskStep) => {
        const sanitizedStep = sanitizeTaskStep(step)
        const hasStep = assistantSteps.some((s) => s.id === sanitizedStep.id)
        assistantSteps = sanitizeTaskSteps(
          hasStep
            ? assistantSteps.map((s) => (s.id === sanitizedStep.id ? mergeAndSanitizeTaskStep(s, sanitizedStep) : s))
            : [...assistantSteps, sanitizedStep]
        )

        useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
          content: assistantText + pendingText,
          steps: assistantSteps,
        })
      }

      const patchStep = (stepId: string, patch: Partial<TaskStep>) => {
        const hasStep = assistantSteps.some((s) => s.id === stepId)
        if (!hasStep) {
          upsertStep({
            id: stepId,
            title: patch.title || patch.toolName || '步骤',
            status: patch.status || 'running',
            startTime: patch.startTime,
            endTime: patch.endTime,
            toolName: patch.toolName,
            input: patch.input,
            output: patch.output,
            error: patch.error,
          })
          return
        }
        assistantSteps = sanitizeTaskSteps(assistantSteps.map((s) => (s.id === stepId ? mergeAndSanitizeTaskStep(s, patch) : s)))
        useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
          content: assistantText + pendingText,
          steps: assistantSteps,
        })
      }

      const createThinkingStepIfNeeded = (toolName: string) => {
        if (thinkingStepId) return
        thinkingStepId = generateId()
        thinkingStartTime = new Date().toISOString()
        thinkingBuffer = ''
        upsertStep({
          id: thinkingStepId,
          title: `思考中：${toolName || '任务'}`,
          status: 'running',
          startTime: thinkingStartTime,
          toolName: toolName || undefined,
          input: undefined,
          output: '',
        })
      }

      const appendThinking = (text: string) => {
        if (!thinkingStepId) return
        thinkingBuffer = appendCappedText(thinkingBuffer, text || '', 12000)
        patchStep(thinkingStepId, { output: thinkingBuffer })
      }

      const completeThinkingStep = () => {
        if (!thinkingStepId) return
        patchStep(thinkingStepId, { status: 'completed', endTime: new Date().toISOString() })
        thinkingStepId = null
        thinkingStartTime = null
        thinkingBuffer = ''
      }

      const startSubAgentThinking = (kp: string, toolName: string) => {
        const existing = subThinkingStepIdByKP[kp]
        if (existing) return existing
        const id = generateId()
        const startTime = new Date().toISOString()
        subThinkingStepIdByKP[kp] = id
        subThinkingStartTimeByKP[kp] = startTime
        subThinkingBufferByKP[kp] = ''
        upsertSubAgentStep(kp, {
          id,
          title: `思考中：${toolName || '子任务'}`,
          status: 'running',
          startTime,
          toolName: toolName || undefined,
          input: undefined,
          output: '',
        })
        return id
      }

      const appendSubAgentThinking = (kp: string, text: string) => {
        const id = subThinkingStepIdByKP[kp]
        if (!id) return
        const next = appendCappedText(subThinkingBufferByKP[kp] || '', text || '', 8000)
        subThinkingBufferByKP[kp] = next
        patchSubAgentStep(kp, id, { output: next })
      }

      const completeSubAgentThinking = (kp: string) => {
        const id = subThinkingStepIdByKP[kp]
        if (!id) return
        patchSubAgentStep(kp, id, { status: 'completed', endTime: new Date().toISOString() })
        delete subThinkingStepIdByKP[kp]
        delete subThinkingStartTimeByKP[kp]
        delete subThinkingBufferByKP[kp]
      }

      const startSubAgent = (kp: string) => {
        runningSubAgentKP = kp
        activeSubAgentKPs.add(kp)
        setActiveSubAgentTab(kp)
        setSubAgentActivities((prev) => {
          const exists = prev.some((a) => a.knowledgePoint === kp)
          if (exists) {
            return prev.map((a) => (a.knowledgePoint === kp ? { ...a, status: 'running' as const } : a))
          }
          return [...prev, { knowledgePoint: kp, status: 'running' as const, steps: [] }]
        })
      }

      const endSubAgent = (kp: string) => {
        activeSubAgentKPs.delete(kp)
        if (runningSubAgentKP === kp) runningSubAgentKP = null
        completeSubAgentThinking(kp)
        setSubAgentActivities((prev) =>
          prev.map((a) => {
            if (a.knowledgePoint !== kp) return a
            const steps = sanitizeTaskSteps(
              a.steps.map((s) =>
                s.status === 'running'
                  ? mergeAndSanitizeTaskStep(s, { status: 'completed' as const, endTime: new Date().toISOString() })
                  : s
              )
            )
            const hasFailed = steps.some((s) => s.status === 'failed')
            return { ...a, status: hasFailed ? 'failed' : 'completed', steps }
          })
        )
      }

      const handleStreamEvent = (env: unknown) => {
        const envelope = toRecord(env)
        const kind = toText(envelope.type).trim()
        const payload = toRecord(envelope.data)

        if (kind === 'ping') {
          // Keep the conversation marked as resumable while running.
          if (serverTaskId) {
            useConversationStore.getState().updateConversation(conversationId, {
              activeStream: { taskType: 'study_materials', taskId: serverTaskId, assistantMessageId, lastSeq },
              resumable: true,
            })
          }
          return
        }

        if (kind === 'task_started') {
          const tid = toText(payload?.taskId)
          if (tid) serverTaskId = tid
          setIsGeneratingLocal(true)
          if (serverTaskId) {
            useConversationStore.getState().updateConversation(conversationId, {
              activeStream: { taskType: 'study_materials', taskId: serverTaskId, assistantMessageId, lastSeq },
              resumable: true,
            })
          }
          return
        }

        if (kind === 'text_delta') {
          const text = toText(payload?.content)
          if (text) {
            pendingText += text
            scheduleFlush()
          }
          return
        }

        if (kind === 'tool_start' || kind === 'tool_call') {
          const toolName = toText(payload?.tool) || toText(payload?.name)
          const title = toText(payload?.title) || toolName || '工具调用'
          const stepId = toText(payload?.step_id) || generateId()
          const input = getPayloadInput(payload)
          const step: TaskStep = {
            id: stepId,
            title,
            status: 'running',
            startTime: toText(payload?.start_time) || new Date().toISOString(),
            toolName: toolName || undefined,
            input,
          }
          upsertStep(step)

          const kp = getPayloadKnowledgePoint(payload, stepId)
          if (kp) {
            startSubAgent(kp)
            subAgentStepKPById[stepId] = kp
            if (kind === 'tool_call') {
              upsertSubAgentStep(kp, step)
            } else {
              startSubAgentThinking(kp, toolName)
            }
          } else {
            createThinkingStepIfNeeded(toolName)
          }
          return
        }

        if (kind === 'tool_delta' || kind === 'thinking') {
          const text = toText(payload?.content)
          if (text) {
            const kp = getPayloadKnowledgePoint(payload) || getSoleActiveSubAgent()
            if (kp) {
              startSubAgentThinking(kp, 'thinking')
              appendSubAgentThinking(kp, text)
            } else {
              createThinkingStepIfNeeded('thinking')
              appendThinking(text)
            }
          }
          return
        }

        if (kind === 'tool_end' || kind === 'tool_result') {
          const stepId = toText(payload?.step_id)
          const status = toTaskStepStatus(
            toText(payload.status) || (payload.success === false ? 'failed' : 'completed'),
            'completed'
          )
          const endTime = toText(payload?.end_time) || new Date().toISOString()
          const output = payload?.output ?? payload?.result
          const error = toText(payload?.error || payload?.message) || undefined
          const toolName = toText(payload?.tool) || toText(payload?.name)

          if (stepId) {
            patchStep(stepId, { status, endTime, output, error })
          }

          const kp = getPayloadKnowledgePoint(payload, stepId || undefined)
          if (kp && stepId) {
            patchSubAgentStep(kp, stepId, {
              status,
              endTime,
              output,
              error,
              toolName: toolName || undefined,
            })
            completeSubAgentThinking(kp)
            if (status === 'failed') {
              updateSubAgentStatus(kp)
            } else if (!activeSubAgentKPs.has(kp)) {
              updateSubAgentStatus(kp)
            }
          }

          const kps = normalizeKnowledgePoints(toRecord(output).knowledge_points)
          if ((toolName === 'split_knowledge_points' || toolName === 'review_knowledge_points') && kps.length > 0) {
            initializeSubAgentActivities(kps)
          } else if (kind === 'tool_end' && kps.length === 1) {
            endSubAgent(kps[0])
          } else if (!kp) {
            completeThinkingStep()
          }
          return
        }

        if (kind === 'subagent_start') {
          const kp = toText(payload?.knowledge_point || payload?.knowledgePoint)
          if (kp) startSubAgent(kp)
          return
        }

        if (kind === 'subagent_end') {
          const kp = toText(payload?.knowledge_point || payload?.knowledgePoint)
          if (kp) endSubAgent(kp)
          return
        }

        if (kind === 'step') {
          const rawStep = payload.step
          if (rawStep && typeof rawStep === 'object' && !Array.isArray(rawStep)) {
            const step = toRecord(rawStep)
            const stepId = toText(step.id) || generateId()
            const status = toTaskStepStatus(step.status, 'running')
            upsertStep({
              id: stepId,
              title: toText(step.title) || '步骤',
              status,
              startTime: toText(step.startTime) || undefined,
              endTime: toText(step.endTime) || undefined,
              toolName: toText(step.toolName) || undefined,
              input: step.input,
              output: step.output,
              error: toText(step.error) || undefined,
            })
          }
          return
        }

        if (kind === 'result') {
          // Some workflows emit a final result payload.
          return
        }

        if (kind === 'done') {
          done = true
          flushAssistant()
          if (serverTaskId) {
            useConversationStore.getState().updateConversation(conversationId, {
              activeStream: undefined,
              resumable: false,
              status: 'active',
            })
          }
          setIsGeneratingLocal(false)
          if (localTaskId) {
            useTaskStore.getState().completeTask(localTaskId)
          }
          return
        }

        if (kind === 'error') {
          const msg = formatStudyMaterialsError(toText(payload?.message) || '生成失败')
          if (msg) setError(msg)
          done = true
          flushAssistant()
          setIsGeneratingLocal(false)
          if (localTaskId) {
            useTaskStore.getState().failTask(localTaskId, msg)
          }
          if (serverTaskId) {
            useConversationStore.getState().updateConversation(conversationId, {
              activeStream: undefined,
              resumable: false,
            })
          }
        }
      }

      setIsGeneratingLocal(true)
      setError(null)

      const handleStreamData = (data: unknown) => {
        const env = normalizeSseEnvelope(data)
        const seq = typeof env.seq === 'number' ? env.seq : Number(env.seq || 0)
        if (Number.isFinite(seq) && seq > lastSeq) lastSeq = seq
        if (serverTaskId) {
          useConversationStore.getState().updateConversation(conversationId, {
            activeStream: { taskType: 'study_materials', taskId: serverTaskId, assistantMessageId, lastSeq },
            resumable: true,
          })
        }
        handleStreamEvent(env)
      }

      const handleStreamError = (err: unknown) => {
        const normalizedError =
          err instanceof ApiError
            ? err
            : isApiError(err)
              ? new ApiError({
                  code: err.code,
                  message: formatStudyMaterialsError(err.message || '生成失败'),
                  status: err.status,
                  requestId: err.requestId,
                  detail: err.detail,
                  retriable: err.retriable,
                  actions: err.actions,
                })
              : formatStudyMaterialsError(err instanceof Error ? err.message : toText(toRecord(err).message) || '生成失败')

        const msg = isApiError(normalizedError) ? normalizedError.message : String(normalizedError || '生成失败')
        setError(normalizedError)
        if (localTaskId) {
          useTaskStore.getState().failTask(localTaskId, msg)
        }
        useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
          content: `出错：${msg}`,
          steps: assistantSteps,
        })
        // Keep activeStream so the user can refresh/reconnect.
        setIsGeneratingLocal(false)
      }

      const handleStreamComplete = () => {
        if (streamAbortRef.current !== controller) return
        if (!done) {
          // Connection closed unexpectedly: keep the task resumable.
          setIsGeneratingLocal(false)
        }
        streamAbortRef.current = null
      }

      // Use WebSocket for the unified task stream (`GET /tasks/{id}/stream?after_seq=N`).
      // This avoids SSE timeouts during long-running studies and gives durable
      // refresh-resume via the persistent connection.
      const taskStream = parseTaskStreamUrl(request.url, request.method)
      if (taskStream) {
        if (taskStream.taskId) serverTaskId = taskStream.taskId
        const cleanup = streamTaskWs(
          taskStream.taskId,
          taskStream.afterSeq,
          handleStreamData,
          handleStreamError,
          handleStreamComplete,
          { signal: controller.signal },
        )
        // Wire abort to cleanup the WS connection.
        if (controller.signal.aborted) {
          cleanup()
        } else {
          controller.signal.addEventListener('abort', () => cleanup())
        }
        return
      }

      void fetchSSERequest(
        request.url,
        { method: request.method, body: request.body, signal: controller.signal, inactivityTimeoutMs: 120_000 },
        handleStreamData,
        handleStreamError,
        handleStreamComplete,
      )
    },
    [abortActiveStream, setActiveSubAgentTab, setError, setIsGeneratingLocal, setSubAgentActivities]
  )

  return {
    abortActiveStream,
    runStudyMaterialsStream,
    streamKeyRef,
  }
}
