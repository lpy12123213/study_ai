import { useCallback, useEffect, useRef, useState } from 'react'
import type { DeepThinkEvent, DeepThinkNode } from '@/api/deepthink'
import { solveDeepThinkStream } from '@/api/deepthink'
import { cancelTask } from '@/api/tasks'
import { readString } from '@/lib/record'

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
  const [taskId, setTaskId] = useState<string>('')
  const [nodes, setNodes] = useState<Record<string, ThinkingNode>>({})
  const [bestPath, setBestPath] = useState<string[]>([])
  const [answer, setAnswer] = useState<string>('')
  const [metrics, setMetrics] = useState<DeepThinkMetrics>(EMPTY_METRICS)
  const [error, setError] = useState<string | null>(null)
  const [config, setConfig] = useState<Record<string, unknown> | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const taskIdRef = useRef<string>('')

  const nodesRef = useRef<Record<string, ThinkingNode>>({})
  const nodesFlushRafRef = useRef<number | null>(null)

  const answerRef = useRef<string>('')
  const answerFlushRafRef = useRef<number | null>(null)

  const flushNodes = useCallback(() => {
    nodesFlushRafRef.current = null
    setNodes({ ...nodesRef.current })
  }, [])

  const scheduleNodesFlush = useCallback(() => {
    if (nodesFlushRafRef.current != null) return
    nodesFlushRafRef.current = requestAnimationFrame(() => {
      flushNodes()
    })
  }, [flushNodes])

  const flushAnswer = useCallback(() => {
    answerFlushRafRef.current = null
    setAnswer(answerRef.current)
  }, [])

  const scheduleAnswerFlush = useCallback(() => {
    if (answerFlushRafRef.current != null) return
    answerFlushRafRef.current = requestAnimationFrame(() => {
      flushAnswer()
    })
  }, [flushAnswer])

  const disconnectStream = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
  }, [])

  const cancel = useCallback((reason = 'cancelled') => {
    disconnectStream()
    if (taskIdRef.current) {
      cancelTask(taskIdRef.current).catch(() => {
        // ignore: page still shows partial progress
      })
    }
    // Keep existing nodes/answer so users can inspect partial progress.
    if (status === 'searching' || status === 'answering') {
      setStatus('idle')
      if (reason && reason !== 'cancelled') {
        // no-op: keep UX quiet for normal cancels
      }
    }
  }, [disconnectStream, status])

  const reset = useCallback(() => {
    cancel('reset')
    setStatus('idle')
    setTaskId('')
    taskIdRef.current = ''
    nodesRef.current = {}
    setNodes({})
    setBestPath([])
    answerRef.current = ''
    setAnswer('')
    setMetrics(EMPTY_METRICS)
    setError(null)
    setConfig(null)
  }, [cancel])

  const applyEvent = useCallback((event: DeepThinkEvent) => {
    if (typeof event.taskId === 'string') {
      const tid = event.taskId.trim()
      if (tid && tid !== taskIdRef.current) {
        taskIdRef.current = tid
        setTaskId(tid)
      }
    }
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
        nodesRef.current = {}
        answerRef.current = ''
        setNodes({})
        setAnswer('')
        setBestPath([])
        return
      }
      case 'node_generated': {
        const n = event.node
        const existing = nodesRef.current[n.id]
        nodesRef.current[n.id] = existing
          ? {
              ...existing,
              ...n,
              status: existing.status,
              score: existing.score,
              evalReasoning: existing.evalReasoning,
              issues: existing.issues,
              createdAt: existing.createdAt,
            }
          : {
              ...n,
              score: null,
              evalReasoning: null,
              issues: [],
              createdAt: Date.now(),
            }
        scheduleNodesFlush()
        return
      }
      case 'node_evaluated': {
        const existing = nodesRef.current[event.nodeId]
        if (!existing) return
        nodesRef.current[event.nodeId] = {
          ...existing,
          score: typeof event.score === 'number' ? event.score : existing.score,
          evalReasoning:
            typeof event.evalReasoning === 'string' ? event.evalReasoning : existing.evalReasoning,
          issues: Array.isArray(event.issues)
            ? event.issues.filter((x) => typeof x === 'string')
            : existing.issues,
          status: event.status || existing.status,
        }
        scheduleNodesFlush()
        return
      }
      case 'node_pruned': {
        const existing = nodesRef.current[event.nodeId]
        if (!existing) return
        nodesRef.current[event.nodeId] = {
          ...existing,
          score: typeof event.score === 'number' ? event.score : existing.score,
          status: 'pruned',
          evalReasoning:
            typeof event.reason === 'string' && event.reason.trim()
              ? event.reason
              : existing.evalReasoning,
        }
        scheduleNodesFlush()
        return
      }
      case 'node_selected': {
        const existing = nodesRef.current[event.nodeId]
        if (!existing) return
        nodesRef.current[event.nodeId] = { ...existing, status: 'selected' }
        scheduleNodesFlush()
        return
      }
      case 'search_complete': {
        const existing = nodesRef.current[event.nodeId]
        if (!existing) return
        nodesRef.current[event.nodeId] = { ...existing, status: 'final' }
        scheduleNodesFlush()
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
          const nodeId = readString(p, 'nodeId')
          if (nodeId) ids.push(nodeId)
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
        answerRef.current += event.content || ''
        scheduleAnswerFlush()
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
  }, [scheduleAnswerFlush, scheduleNodesFlush])

  const solve = useCallback(
    (question: string, opts?: { subject?: string; imageUrl?: string }) => {
      cancel('replaced')
      reset()
      setStatus('searching')
      setError(null)

      const controller = new AbortController()
      abortRef.current = controller

      solveDeepThinkStream(
        { question, subject: opts?.subject, imageUrl: opts?.imageUrl },
        (event) => {
          applyEvent(event)
        },
        (err) => {
          if (controller.signal.aborted) return
          setStatus('error')
          setError(err.message)
          abortRef.current = null
        },
        () => {
          // Stream completed ([DONE]) - status is usually set by 'done'
          abortRef.current = null
        },
        { signal: controller.signal },
      )
    },
    [applyEvent, cancel, reset],
  )

  useEffect(() => {
    return () => {
      disconnectStream()
      if (nodesFlushRafRef.current != null) {
        cancelAnimationFrame(nodesFlushRafRef.current)
        nodesFlushRafRef.current = null
      }
      if (answerFlushRafRef.current != null) {
        cancelAnimationFrame(answerFlushRafRef.current)
        answerFlushRafRef.current = null
      }
    }
  }, [disconnectStream])

  return {
    status,
    taskId,
    nodes,
    bestPath,
    answer,
    metrics,
    error,
    config,
    solve,
    cancel,
    reset,
  }
}

