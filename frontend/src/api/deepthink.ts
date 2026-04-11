import { apiClient } from '@/api/client'
import { streamTask, type TaskStreamEvent } from '@/api/tasks'

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
      const taskId = String((res.data as any)?.taskId || '').trim()
      if (!taskId) throw new Error('missing_task_id')

      streamTask(
        taskId,
        0,
        (evt: TaskStreamEvent) => {
          // DeepThink domain events are emitted as {type, ...fields} in backend;
          // the unified TaskRuntime wraps domain fields under `data`.
          if (evt.type === 'ping' || evt.type === 'step') return

          const data = evt.data && typeof evt.data === 'object' ? (evt.data as Record<string, unknown>) : {}
          if (evt.type === 'error') {
            const message =
              typeof (data as any)?.message === 'string'
                ? String((data as any).message)
                : typeof (data as any)?.error === 'string'
                  ? String((data as any).error)
                  : 'deepthink_failed'
            onEvent({ taskId: evt.taskId, type: 'error', message } as DeepThinkEvent)
            return
          }
          onEvent({ taskId: evt.taskId, type: evt.type as any, ...(data as any) } as DeepThinkEvent)
        },
        onError,
        onComplete,
        { signal: options?.signal },
      )
    })
    .catch((err: any) => {
      const message = typeof err?.message === 'string' ? err.message : 'request_failed'
      onError?.(err instanceof Error ? err : new Error(message))
    })
}

