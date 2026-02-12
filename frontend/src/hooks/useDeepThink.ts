import { useCallback, useState } from 'react'
import type { DeepThinkEvent, DeepThinkNode } from '@/api/deepthink'
import { solveDeepThinkStream } from '@/api/deepthink'

export type DeepThinkStatus = 'idle' | 'searching' | 'answering' | 'done' | 'error'

export interface ThinkingNode extends DeepThinkNode {
  score: number | null
  evalReasoning: string | null
  issues: string[]
  createdAt: number
}

export interface DeepThinkMetrics {
  currentDepth: number
  frontierSize: number
  totalNodes: number
  elapsed: number
  bestScore: number
  bestLeafId: string
}

const EMPTY_METRICS: DeepThinkMetrics = {
  currentDepth: 0,
  frontierSize: 0,
  totalNodes: 0,
  elapsed: 0,
  bestScore: 0,
  bestLeafId: '',
}

export function useDeepThink() {
  const [status, setStatus] = useState<DeepThinkStatus>('idle')
  const [nodes, setNodes] = useState<Record<string, ThinkingNode>>({})
  const [bestPath, setBestPath] = useState<string[]>([])
  const [answer, setAnswer] = useState<string>('')
  const [metrics, setMetrics] = useState<DeepThinkMetrics>(EMPTY_METRICS)
  const [error, setError] = useState<string | null>(null)
  const [config, setConfig] = useState<Record<string, unknown> | null>(null)

  const reset = useCallback(() => {
    setStatus('idle')
    setNodes({})
    setBestPath([])
    setAnswer('')
    setMetrics(EMPTY_METRICS)
    setError(null)
    setConfig(null)
  }, [])

  const applyEvent = useCallback((event: DeepThinkEvent) => {
    switch (event.type) {
      case 'search_start': {
        setStatus('searching')
        setConfig(event.config || null)
        setMetrics((m) => ({
          ...m,
          currentDepth: 0,
          frontierSize: 0,
          totalNodes: 0,
          elapsed: 0,
          bestScore: 0,
          bestLeafId: '',
        }))
        return
      }
      case 'node_generated': {
        const n = event.node
        setNodes((prev) => ({
          ...prev,
          [n.id]: {
            ...n,
            score: prev[n.id]?.score ?? null,
            evalReasoning: prev[n.id]?.evalReasoning ?? null,
            issues: prev[n.id]?.issues ?? [],
            createdAt: prev[n.id]?.createdAt ?? Date.now(),
          },
        }))
        return
      }
      case 'node_evaluated': {
        setNodes((prev) => {
          const existing = prev[event.nodeId]
          if (!existing) return prev
          return {
            ...prev,
            [event.nodeId]: {
              ...existing,
              score: typeof event.score === 'number' ? event.score : existing.score,
              evalReasoning:
                typeof event.evalReasoning === 'string'
                  ? event.evalReasoning
                  : existing.evalReasoning,
              issues: Array.isArray(event.issues)
                ? event.issues.filter((x) => typeof x === 'string')
                : existing.issues,
              status: event.status || existing.status,
            },
          }
        })
        return
      }
      case 'node_pruned': {
        setNodes((prev) => {
          const existing = prev[event.nodeId]
          if (!existing) return prev
          return {
            ...prev,
            [event.nodeId]: {
              ...existing,
              score: typeof event.score === 'number' ? event.score : existing.score,
              status: 'pruned',
              evalReasoning:
                typeof event.reason === 'string' && event.reason.trim()
                  ? event.reason
                  : existing.evalReasoning,
            },
          }
        })
        return
      }
      case 'node_selected': {
        setNodes((prev) => {
          const existing = prev[event.nodeId]
          if (!existing) return prev
          return {
            ...prev,
            [event.nodeId]: {
              ...existing,
              status: 'selected',
            },
          }
        })
        return
      }
      case 'search_complete': {
        setNodes((prev) => {
          const existing = prev[event.nodeId]
          if (!existing) return prev
          return {
            ...prev,
            [event.nodeId]: {
              ...existing,
              status: 'final',
            },
          }
        })
        return
      }
      case 'depth_complete': {
        setMetrics((m) => ({
          ...m,
          currentDepth: event.depth,
          frontierSize: event.frontierSize,
          totalNodes: event.totalNodes,
        }))
        return
      }
      case 'best_path': {
        const ids: string[] = []
        for (const p of event.path || []) {
          const nodeId = (p as any)?.nodeId
          if (typeof nodeId === 'string') ids.push(nodeId)
        }
        setBestPath(ids)
        setMetrics((m) => ({
          ...m,
          elapsed: typeof event.elapsed === 'number' ? event.elapsed : m.elapsed,
          bestScore: typeof event.bestScore === 'number' ? event.bestScore : m.bestScore,
          bestLeafId: typeof event.bestLeafId === 'string' ? event.bestLeafId : m.bestLeafId,
        }))
        return
      }
      case 'answer_start': {
        setStatus('answering')
        return
      }
      case 'answer_delta': {
        setAnswer((prev) => prev + (event.content || ''))
        return
      }
      case 'done': {
        setStatus('done')
        setMetrics((m) => ({
          ...m,
          elapsed: typeof event.elapsed === 'number' ? event.elapsed : m.elapsed,
          bestScore: typeof event.bestScore === 'number' ? event.bestScore : m.bestScore,
          bestLeafId: typeof event.bestLeafId === 'string' ? event.bestLeafId : m.bestLeafId,
          totalNodes: typeof event.totalNodes === 'number' ? event.totalNodes : m.totalNodes,
        }))
        return
      }
      case 'error': {
        setStatus('error')
        setError(event.message || '未知错误')
        return
      }
      default:
        return
    }
  }, [])

  const solve = useCallback(
    (question: string, opts?: { subject?: string; imageUrl?: string }) => {
      reset()
      setStatus('searching')
      setError(null)

      solveDeepThinkStream(
        { question, subject: opts?.subject, imageUrl: opts?.imageUrl },
        (event) => {
          applyEvent(event)
        },
        (err) => {
          setStatus('error')
          setError(err.message)
        },
        () => {
          // Stream completed ([DONE]) - status is usually set by 'done'
        },
      )
    },
    [applyEvent, reset],
  )

  return {
    status,
    nodes,
    bestPath,
    answer,
    metrics,
    error,
    config,
    solve,
    reset,
  }
}

