import { useCallback, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { normalizeSseEnvelope, type SseEnvelope } from '@/lib/sse'
import { generateId } from '@/lib/utils'
import { fetchSSE } from '@/api/client'
import { useTaskStore } from '@/stores/useTaskStore'
import {
  crawlQuestions,
  generateQuestions,
  type QuestionLibraryDraftQuestion,
  type CrawlQuestionsPayload,
  type GenerateQuestionsPayload,
  type QuestionLibraryListItem,
  type QuestionLibraryListResponse,
  type ScoreQuestionLibraryBatchPayload,
} from '@/api/questionLibrary'
import type { TaskStep } from '@/types'
import type { QuestionLibraryFilters } from '@/pages/questionLibrary/hooks/useQuestionLibrary'

export type QuestionLibraryTaskKind = 'crawl' | 'generate' | 'score'

export interface QuestionLibraryTaskMeta {
  taskId: string
  kind: QuestionLibraryTaskKind
  status: 'running' | 'completed' | 'failed'
  progress: number
  stage?: string
  error?: string
  lastSeq: number
}

export interface QuestionLibraryDraftPreview {
  previewId: string
  subject: string
  topic: string
  count: number
  draftQuestions: QuestionLibraryDraftQuestion[]
  taskId: string
}

function nowIso(): string {
  return new Date().toISOString()
}

function coerceNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const n = Number(value)
    if (Number.isFinite(n)) return n
  }
  return null
}

function shouldIncludeItem(item: any, filters: QuestionLibraryFilters): boolean {
  const subj = String(item?.subject || '').trim()
  const origin = String(item?.origin || '').trim()
  const hidden = Boolean(item?.hidden)

  if (filters.subject && subj && subj !== filters.subject) return false
  if (filters.origin !== 'all' && origin && origin !== filters.origin) return false

  if (filters.hidden === '0' && hidden) return false
  if (filters.hidden === '1' && !hidden) return false

  // If the user is searching, incremental inserts can be misleading; let the final refresh handle it.
  if (filters.q.trim()) return false

  return true
}

export function useQuestionLibraryTasks(options: {
  filters: QuestionLibraryFilters
  onDone?: () => void
}) {
  const { filters, onDone } = options
  const queryClient = useQueryClient()

  const { startTask, addStep, updateStep, completeTask, failTask, getTaskSteps } = useTaskStore()

  const [tasks, setTasks] = useState<QuestionLibraryTaskMeta[]>([])
  const [draftPreview, setDraftPreview] = useState<QuestionLibraryDraftPreview | null>(null)

  const stageByTaskIdRef = useRef<Record<string, string>>({})
  const seenStepIdsRef = useRef<Record<string, Record<string, boolean>>>({})

  const clearDraftPreview = useCallback(() => setDraftPreview(null), [])

  const normalizeDraftQuestions = useCallback((input: unknown): QuestionLibraryDraftQuestion[] => {
    const list = Array.isArray(input) ? (input as any[]) : []
    const out: QuestionLibraryDraftQuestion[] = []
    for (const it of list) {
      if (!it || typeof it !== 'object') continue
      const qid = String((it as any).question_id || (it as any).questionId || '').trim()
      const stem = String((it as any).stem || '').trim()
      const answer = String((it as any).answer || '').trim()
      const analysis = String((it as any).analysis || '').trim()
      if (!qid) continue
      out.push({
        question_id: qid,
        stem,
        answer,
        analysis,
        keep: (it as any).keep === false ? false : true,
      })
    }
    return out
  }, [])

  const upsertTask = useCallback((meta: Partial<QuestionLibraryTaskMeta> & { taskId: string }) => {
    setTasks((prev) => {
      const existing = prev.find((t) => t.taskId === meta.taskId)
      if (!existing) {
        const next: QuestionLibraryTaskMeta = {
          taskId: meta.taskId,
          kind: (meta.kind || 'crawl') as any,
          status: meta.status || 'running',
          progress: meta.progress ?? 0,
          stage: meta.stage,
          error: meta.error,
          lastSeq: meta.lastSeq ?? 0,
        }
        return [next, ...prev].slice(0, 6)
      }
      return prev.map((t) => (t.taskId === meta.taskId ? { ...t, ...meta } : t))
    })
  }, [])

  const patchListOnItemSaved = useCallback(
    (item: any) => {
      if (!shouldIncludeItem(item, filters)) {
        return
      }

      queryClient.setQueryData(['questionLibrary', filters], (prev: unknown) => {
        const data = prev as QuestionLibraryListResponse | undefined
        if (!data || !Array.isArray(data.items)) return prev
        const qid = String(item?.question_id || '').trim()
        if (!qid) return prev

        const merged: QuestionLibraryListItem = {
          ...(data.items.find((x) => String(x.question_id || '').trim() === qid) || {}),
          ...(item as any),
        }

        const rest = data.items.filter((x) => String(x.question_id || '').trim() !== qid)
        return {
          ...data,
          items: [merged, ...rest].slice(0, Math.max(10, data.limit || 80)),
        }
      })
    },
    [filters, queryClient]
  )

  const handleEnvelope = useCallback(
    (taskId: string, env: SseEnvelope) => {
      const id = String(env.taskId || taskId || '').trim() || taskId
      const seq = typeof env.seq === 'number' && Number.isFinite(env.seq) ? env.seq : null
      if (seq && seq > 0) upsertTask({ taskId: id, lastSeq: seq })

      const payload = (env.data || {}) as any

      if (env.type === 'step' && payload?.step) {
        const step = payload.step as TaskStep
        if (!step?.id) return

        const seenForTask = (seenStepIdsRef.current[id] ||= {})
        if (seenForTask[step.id]) {
          updateStep(id, step.id, step)
        } else {
          seenForTask[step.id] = true
          addStep(id, step)
        }
        return
      }

      if (env.type === 'progress') {
        const progress = coerceNumber(payload?.progress)
        const stage = typeof payload?.stage === 'string' ? payload.stage.trim() : ''
        if (typeof progress === 'number') upsertTask({ taskId: id, progress })
        if (stage) {
          upsertTask({ taskId: id, stage })

          const prevStage = stageByTaskIdRef.current[id] || ''
          if (prevStage && prevStage !== stage) {
            updateStep(id, `stage:${prevStage}`, { status: 'completed', endTime: nowIso() })
          }

          if (!prevStage || prevStage !== stage) {
            stageByTaskIdRef.current[id] = stage
            const seenForTask = (seenStepIdsRef.current[id] ||= {})
            const stepId = `stage:${stage}`
            const step: TaskStep = {
              id: stepId,
              title: stage,
              status: 'running',
              toolName: 'question_library',
              startTime: nowIso(),
            }
            if (seenForTask[stepId]) {
              updateStep(id, stepId, step)
            } else {
              seenForTask[stepId] = true
              addStep(id, step)
            }
          }
        }
        return
      }

      if (env.type === 'item_saved') {
        patchListOnItemSaved(payload?.item)
        return
      }

      if (env.type === 'done') {
        const previewId = String(payload?.preview_id || payload?.previewId || '').trim()
        if (previewId) {
          const drafts = normalizeDraftQuestions(payload?.draft_questions || payload?.draftQuestions)
          if (drafts.length > 0) {
            setDraftPreview({
              previewId,
              subject: String(payload?.subject || '').trim(),
              topic: String(payload?.topic || '').trim(),
              count: Math.max(0, Number(payload?.count || drafts.length || 0)) || drafts.length,
              draftQuestions: drafts,
              taskId: id,
            })
          }
        }
        upsertTask({ taskId: id, status: 'completed', progress: 100 })
        completeTask(id)
        onDone?.()
        return
      }

      if (env.type === 'error') {
        const msg = String(payload?.error || payload?.message || '任务失败').trim() || '任务失败'
        upsertTask({ taskId: id, status: 'failed', error: msg })
        failTask(id, msg)
        return
      }
    },
    [addStep, completeTask, failTask, normalizeDraftQuestions, onDone, patchListOnItemSaved, upsertTask, updateStep]
  )

  const runCrawl = useCallback(
    (payload: Omit<CrawlQuestionsPayload, 'task_id'> & { task_id?: string }) => {
      const taskId = String(payload.task_id || '').trim() || `ql-crawl-${generateId()}`
      startTask(taskId)
      upsertTask({ taskId, kind: 'crawl', status: 'running', progress: 0, stage: '爬取入库', lastSeq: 0 })

      crawlQuestions(
        { ...payload, task_id: taskId },
        (env) => handleEnvelope(taskId, normalizeSseEnvelope(env)),
        (err) => {
          upsertTask({ taskId, status: 'failed', error: err.message })
          failTask(taskId, err.message)
        },
        () => {
          // If stream ended without a terminal event, mark as failed so the UI can retry.
          const steps = getTaskSteps(taskId)
          const hasTerminal = steps.some((s) => s.status === 'failed') || steps.some((s) => s.status === 'completed')
          if (!hasTerminal) {
            failTask(taskId, 'Task ended unexpectedly')
            upsertTask({ taskId, status: 'failed', error: 'Task ended unexpectedly' })
          }
        }
      )

      return taskId
    },
    [failTask, getTaskSteps, handleEnvelope, startTask, upsertTask]
  )

  const runGenerate = useCallback(
    (payload: Omit<GenerateQuestionsPayload, 'task_id'> & { task_id?: string }) => {
      const taskId = String(payload.task_id || '').trim() || `ql-gen-${generateId()}`
      clearDraftPreview()
      startTask(taskId)
      upsertTask({ taskId, kind: 'generate', status: 'running', progress: 0, stage: 'AI 出题', lastSeq: 0 })

      generateQuestions(
        { ...payload, task_id: taskId },
        (env) => handleEnvelope(taskId, normalizeSseEnvelope(env)),
        (err) => {
          upsertTask({ taskId, status: 'failed', error: err.message })
          failTask(taskId, err.message)
        },
        () => {
          const steps = getTaskSteps(taskId)
          const hasTerminal = steps.some((s) => s.status === 'failed') || steps.some((s) => s.status === 'completed')
          if (!hasTerminal) {
            failTask(taskId, 'Task ended unexpectedly')
            upsertTask({ taskId, status: 'failed', error: 'Task ended unexpectedly' })
          }
        }
      )

      return taskId
    },
    [clearDraftPreview, failTask, getTaskSteps, handleEnvelope, startTask, upsertTask]
  )

  const runScore = useCallback(
    (payload: Omit<ScoreQuestionLibraryBatchPayload, 'task_id'> & { task_id?: string }) => {
      const taskId = String(payload.task_id || '').trim() || `ql-score-${generateId()}`
      startTask(taskId)
      upsertTask({ taskId, kind: 'score', status: 'running', progress: 0, stage: '评分', lastSeq: 0 })

      fetchSSE(
        '/question-library/score',
        { ...payload, task_id: taskId },
        (data) => handleEnvelope(taskId, normalizeSseEnvelope(data)),
        (err) => {
          upsertTask({ taskId, status: 'failed', error: err.message })
          failTask(taskId, err.message)
        },
        () => {
          const steps = getTaskSteps(taskId)
          const hasTerminal = steps.some((s) => s.status === 'failed') || steps.some((s) => s.status === 'completed')
          if (!hasTerminal) {
            failTask(taskId, 'Task ended unexpectedly')
            upsertTask({ taskId, status: 'failed', error: 'Task ended unexpectedly' })
          }
        }
      )

      return taskId
    },
    [failTask, getTaskSteps, handleEnvelope, startTask, upsertTask]
  )

  const preferredTask = useMemo(() => {
    const running = tasks.find((t) => t.status === 'running')
    return running || tasks[0] || null
  }, [tasks])

  return {
    tasks,
    preferredTask,
    runCrawl,
    runGenerate,
    runScore,
    draftPreview,
    clearDraftPreview,
  }
}
