import { appendCappedText, mergeAndSanitizeTaskStep, sanitizeTaskStep, sanitizeTaskSteps } from '@/lib/taskPayload'
import { generateId } from '@/lib/utils'
import { normalizeKnowledgePoints, toText } from '@/features/generation/studyMaterials/utils'
import { toRecord } from '@/features/generation/studyMaterials/hooks/streamRunner/streamUtils'
import type { StreamRecord, StudyMaterialsStreamCallbacks } from '@/features/generation/studyMaterials/hooks/streamRunner/types'
import type { TaskStep } from '@/types'
import type { SubAgentActivity } from '@/features/generation/studyMaterials/types'

const getPayloadInput = (payload: StreamRecord) => payload.input ?? payload.arguments

type SubAgentTrackerDeps = Pick<StudyMaterialsStreamCallbacks, 'setSubAgentActivities' | 'setActiveSubAgentTab'>

/**
 * Tracks per-knowledge-point SubAgent activities and their streaming "thinking"
 * panels for a single study-materials stream session.
 */
export function createSubAgentTracker({ setSubAgentActivities, setActiveSubAgentTab }: SubAgentTrackerDeps) {
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

  const registerStepKP = (stepId: string, kp: string) => {
    subAgentStepKPById[stepId] = kp
  }

  const hasActiveSubAgent = (kp: string) => activeSubAgentKPs.has(kp)

  return {
    upsertSubAgentStep,
    patchSubAgentStep,
    updateSubAgentStatus,
    initializeSubAgentActivities,
    getPayloadKnowledgePoint,
    getSoleActiveSubAgent,
    startSubAgentThinking,
    appendSubAgentThinking,
    completeSubAgentThinking,
    startSubAgent,
    endSubAgent,
    registerStepKP,
    hasActiveSubAgent,
  }
}

export type SubAgentTracker = ReturnType<typeof createSubAgentTracker>
