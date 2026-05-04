import { apiClient } from '@/api/client'
import { streamTask, type TaskStreamEvent } from '@/api/tasks'

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object')
}

function recordString(value: unknown, key: string): string | undefined {
  if (!isRecord(value)) return undefined
  const item = value[key]
  return typeof item === 'string' ? item : undefined
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return recordString(error, 'message') || 'request_failed'
}

function deepThinkEventType(type: string): DeepThinkEvent['type'] {
  return type as DeepThinkEvent['type']
}

export interface DeepThinkSolveRequest {
  question: string
  subject?: string
  imageUrl?: string
}

export type DeepThinkNodeStatus =
  | 'pending'
  | 'evaluated'
  | 'selected'
  | 'pruned'
  | 'final'
  | string

export interface DeepThinkNode {
  id: string
  parentId: string | null
  depth: number
  thought: string
  reasoning: string
  status: DeepThinkNodeStatus
  isFinal: boolean
}

export type DeepThinkEvent = (
  | {
      type: 'search_start'
      question: string
      subject: string
      config: Record<string, unknown>
    }
  | { type: 'node_generated'; node: DeepThinkNode }
  | {
      type: 'node_evaluated'
      nodeId: string
      score: number
      evalReasoning?: string
      issues?: string[]
      status?: string
    }
  | { type: 'node_pruned'; nodeId: string; score: number; reason?: string }
  | { type: 'node_selected'; nodeId: string }
  | { type: 'depth_complete'; depth: number; frontierSize: number; totalNodes: number }
  | { type: 'search_complete'; nodeId: string; depth: number }
  | {
      type: 'best_path'
      path: Array<Record<string, unknown>>
      bestLeafId: string
      bestScore: number
      elapsed: number
    }
  | { type: 'answer_start' }
  | { type: 'answer_delta'; content: string }
  | {
      type: 'done'
      elapsed: number
      bestScore?: number
      bestLeafId?: string
      totalNodes?: number
    }
  | { type: 'error'; message: string }
  ) & { taskId?: string }

export function solveDeepThinkStream(
  request: DeepThinkSolveRequest,
  onEvent: (event: DeepThinkEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: {
    signal?: AbortSignal
  },
): void {
  const body = {
    question: request.question,
    subject: request.subject,
    image_url: request.imageUrl,
  }

  apiClient
    .post('/tasks/deepthink', body, { signal: options?.signal })
    .then((res) => {
      const taskId = String(recordString(res.data, 'taskId') || '').trim()
      if (!taskId) throw new Error('missing_task_id')

      streamTask(
        taskId,
        0,
        (evt: TaskStreamEvent) => {
          // DeepThink domain events are emitted as {type, ...fields} in backend;
          // the unified TaskRuntime wraps domain fields under `data`.
          if (evt.type === 'ping' || evt.type === 'step') return

          const data = isRecord(evt.data) ? evt.data : {}
          if (evt.type === 'error') {
            const message = recordString(data, 'message') || recordString(data, 'error') || 'deepthink_failed'
            onEvent({ taskId: evt.taskId, type: 'error', message } as DeepThinkEvent)
            return
          }
          onEvent({ taskId: evt.taskId, type: deepThinkEventType(evt.type), ...data } as DeepThinkEvent)
        },
        onError,
        onComplete,
        { signal: options?.signal },
      )
    })
    .catch((err: unknown) => {
      const message = errorMessage(err)
      onError?.(err instanceof Error ? err : new Error(message))
    })
}

