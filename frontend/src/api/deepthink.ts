import { fetchSSE } from './client'

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

export type DeepThinkEvent =
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

export function solveDeepThinkStream(
  request: DeepThinkSolveRequest,
  onEvent: (event: DeepThinkEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: {
    signal?: AbortSignal
  },
): void {
  fetchSSE(
    '/deepthink',
    {
      question: request.question,
      subject: request.subject,
      image_url: request.imageUrl,
    },
    (data) => {
      onEvent(data as DeepThinkEvent)
    },
    onError,
    onComplete,
    { signal: options?.signal },
  )
}

