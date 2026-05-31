import { apiClient } from '@/api/client'
import { useConversationStore } from '@/stores/useConversationStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { readString } from '@/lib/record'
import { formatStudyMaterialsError } from '@/features/generation/studyMaterials/utils'
import type { RunStudyMaterialsStreamOptions } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsStreamRunner'
import type { TriState } from '@/features/generation/studyMaterials/types'

export type ContinueIterationMode =
  | 'improve'
  | 'deepen_research'
  | 'fix_export'
  | 'skip_export'
  | 'resume_failed_stage'
  | 'retry_search'
  | 'replan_from_failure'

/** User-facing message label shown when starting a "continue iteration" run. */
export function continueIterationUserText(mode: ContinueIterationMode): string {
  switch (mode) {
    case 'retry_search':
      return '继续：重试检索（仅重跑检索阶段）'
    case 'resume_failed_stage':
      return '继续：从失败阶段继续'
    case 'replan_from_failure':
      return '继续：重新规划并续跑'
    case 'deepen_research':
      return '继续迭代：加深检索与补充边界/反例'
    case 'fix_export':
      return '继续：修复排版导出'
    case 'skip_export':
      return '继续：跳过导出，完成其余内容'
    default:
      return '继续迭代优化'
  }
}

const toOptionalBool = (v: TriState): boolean | undefined => {
  if (v === 'on') return true
  if (v === 'off') return false
  return undefined
}

export interface BuildGenerateBodyInput {
  prompt: string
  subject: string
  preset: string
  requirements: string
  withQuestions: TriState
  withDiagrams: TriState
  enableExtraTools: TriState
  maxPoints: string
}

/** Builds the `/tasks/study-materials/generate` request body from draft options. */
export function buildGenerateBody(input: BuildGenerateBodyInput): Record<string, unknown> {
  const body: Record<string, unknown> = { query: input.prompt }

  const subjectValue = input.subject.trim()
  if (subjectValue) body.subject = subjectValue
  if (input.preset) body.preset = input.preset
  const requirementsValue = input.requirements.trim()
  if (requirementsValue) body.requirements = requirementsValue

  const withQuestionsValue = toOptionalBool(input.withQuestions)
  if (withQuestionsValue !== undefined) body.with_questions = withQuestionsValue
  const withDiagramsValue = toOptionalBool(input.withDiagrams)
  if (withDiagramsValue !== undefined) body.with_diagrams = withDiagramsValue
  const enableExtraToolsValue = toOptionalBool(input.enableExtraTools)
  if (enableExtraToolsValue !== undefined) body.enable_extra_tools = enableExtraToolsValue

  const maxPointsRaw = input.maxPoints.trim()
  if (maxPointsRaw) {
    const n = Number(maxPointsRaw)
    if (Number.isFinite(n) && n > 0) body.max_points = Math.max(1, Math.min(15, Math.floor(n)))
  }

  return body
}

export interface LaunchStudyMaterialsTaskParams {
  endpoint: string
  body: unknown
  conversationId: string
  assistantMessageId: string
  fallbackErrorMessage: string
  runStudyMaterialsStream: (opts: RunStudyMaterialsStreamOptions) => void
  updateConversation: (id: string, patch: Record<string, unknown>) => void
  setError: (next: unknown) => void
}

/**
 * Posts a study-materials task request and, on success, opens the unified task
 * stream. On failure it writes the error into the assistant message. Shared by
 * the "new generation" and "continue iteration" actions.
 */
export function launchStudyMaterialsTask({
  endpoint,
  body,
  conversationId,
  assistantMessageId,
  fallbackErrorMessage,
  runStudyMaterialsStream,
  updateConversation,
  setError,
}: LaunchStudyMaterialsTaskParams) {
  void apiClient
    .post(endpoint, body)
    .then((res) => {
      const taskId = readString(res.data, 'taskId').trim()
      if (!taskId) throw new Error('missing_task_id')

      useTaskStore.getState().startTask(taskId)
      runStudyMaterialsStream({
        conversationId,
        assistantMessageId,
        request: {
          url: `/tasks/${encodeURIComponent(taskId)}/stream?after_seq=0`,
          method: 'GET',
        },
        localTaskId: taskId,
        initialTaskId: taskId,
        initialSeq: 0,
        streamKey: `${conversationId}:${taskId}`,
      })
    })
    .catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : fallbackErrorMessage
      setError(formatStudyMaterialsError(msg))
      useConversationStore.getState().updateMessage(conversationId, assistantMessageId, {
        content: `出错：${msg}`,
        steps: [],
      })
      updateConversation(conversationId, { updatedAt: new Date().toISOString(), status: 'active' })
    })
}
