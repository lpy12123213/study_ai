import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { normalizeSseEnvelope, type SseEnvelope } from '@/lib/sse'
import { generateId } from '@/lib/utils'
import { isRecord, readNumber, readString, readStringFrom } from '@/lib/record'
import { apiClient } from '@/api/client'
import { streamTask } from '@/api/tasks'
import { taskEventToStep } from '@/components/task/taskEventAdapter'
import { useTaskStore } from '@/stores/useTaskStore'
import {
  crawlQuestions,
  generateQuestions,
  getLatestPendingQuestionLibraryPreview,
  importMediaQuestions,
  type QuestionLibraryDraftQuestion,
  type CrawlQuestionsPayload,
  type GenerateQuestionsPayload,
  type ImportMediaQuestionsPayload,
  type QuestionLibraryListItem,
  type QuestionLibraryListResponse,
  type ScoreQuestionLibraryBatchPayload,
} from '@/api/questionLibrary'
import type { QuestionLibraryFilters } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'

export type QuestionLibraryTaskKind = 'crawl' | 'generate' | 'score' | 'media_import'

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
  sessionId: string
  subject: string
  topic: string
  mode?: 'standard' | 'infinite' | string
  useReferenceQuestions?: boolean
  referenceSource?: 'any' | 'gaokao' | 'mock' | 'joint' | string
  referenceYearRange?: 'all' | '3' | '5' | string
  count: number
  draftQuestions: QuestionLibraryDraftQuestion[]
  taskId: string
}

function shouldIncludeItem(item: unknown, filters: QuestionLibraryFilters): boolean {
  if (!isRecord(item)) return false
  const subj = readString(item, 'subject').trim()
  const origin = readString(item, 'origin').trim()
  const hidden = Boolean(item.hidden)

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
  restoreLatestPreview?: boolean
}) {
  const { filters, onDone, restoreLatestPreview = false } = options
  const queryClient = useQueryClient()

  const { startTask, addStep, updateStep, completeTask, failTask, getTaskSteps } = useTaskStore()

  const [tasks, setTasks] = useState<QuestionLibraryTaskMeta[]>([])
  const [draftPreview, setDraftPreview] = useState<QuestionLibraryDraftPreview | null>(null)
  const [taskEventsByTaskId, setTaskEventsByTaskId] = useState<Record<string, SseEnvelope[]>>({})

  const seenStepIdsRef = useRef<Record<string, Record<string, boolean>>>({})
  const restoreAttemptedRef = useRef(false)

  const clearDraftPreview = useCallback(() => setDraftPreview(null), [])

  const getTaskEvents = useCallback(
    (taskId: string): SseEnvelope[] => {
      const id = String(taskId || '').trim()
      return id ? taskEventsByTaskId[id] || [] : []
    },
    [taskEventsByTaskId]
  )

  const normalizeDraftQuestions = useCallback((input: unknown): QuestionLibraryDraftQuestion[] => {
    const list = Array.isArray(input) ? input : []
    const out: QuestionLibraryDraftQuestion[] = []
    for (const it of list) {
      if (!isRecord(it)) continue
      const qid = readStringFrom(it, ['question_id', 'questionId']).trim()
      const stem = readString(it, 'stem').trim()
      const answer = readString(it, 'answer').trim()
      const analysis = readString(it, 'analysis').trim()
      if (!qid) continue

      const reviewRaw = it.review
      const review = isRecord(reviewRaw)
        ? {
            verdict: readString(reviewRaw, 'verdict').trim(),
            overall_score:
              Number(readNumber(reviewRaw, 'overall_score', NaN) || readNumber(reviewRaw, 'overallScore', 0)) || 0,
            dimensions: Array.isArray(reviewRaw.dimensions)
              ? reviewRaw.dimensions
                  .filter((entry): entry is Record<string, unknown> => isRecord(entry))
                  .map((entry) => ({
                    name: readString(entry, 'name').trim(),
                    score: readNumber(entry, 'score', 0),
                    comment: readString(entry, 'comment').trim(),
                  }))
                  .filter((entry) => entry.name)
              : [],
            highlights: Array.isArray(reviewRaw.highlights)
              ? reviewRaw.highlights.filter((entry): entry is string => typeof entry === 'string')
              : [],
            issues: Array.isArray(reviewRaw.issues)
              ? reviewRaw.issues.filter((entry): entry is string => typeof entry === 'string')
              : [],
            summary: readString(reviewRaw, 'summary').trim(),
            model: readString(reviewRaw, 'model').trim(),
          }
        : null

      const reviewStatusRaw = readStringFrom(it, ['review_status', 'reviewStatus'])
      const allowedReviewStatuses = new Set([
        'pending_review',
        'in_review',
        'approved',
        'rejected',
        'confirmed',
        'committed',
      ])
      const reviewStatus = allowedReviewStatuses.has(reviewStatusRaw)
        ? (reviewStatusRaw as QuestionLibraryDraftQuestion['review_status'])
        : undefined

      out.push({
        question_id: qid,
        stem,
        answer,
        analysis,
        keep: it.keep === false ? false : true,
        review_status: reviewStatus,
        review,
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
          kind: meta.kind ?? 'crawl',
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
    (item: unknown) => {
      if (!shouldIncludeItem(item, filters)) {
        return
      }
      if (!isRecord(item)) return

      queryClient.setQueryData(['questionLibrary', filters], (prev: unknown) => {
        const data = prev as QuestionLibraryListResponse | undefined
        if (!data || !Array.isArray(data.items)) return prev
        const qid = readString(item, 'question_id').trim()
        if (!qid) return prev

        const existing = data.items.find((x) => String(x.question_id || '').trim() === qid)
        const merged: QuestionLibraryListItem = {
          ...(existing || ({} as QuestionLibraryListItem)),
          ...(item as Partial<QuestionLibraryListItem>),
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
      setTaskEventsByTaskId((prev) => {
        const existing = prev[id] || []
        return {
          ...prev,
          [id]: [...existing, env].slice(-400),
        }
      })
      const seq = typeof env.seq === 'number' && Number.isFinite(env.seq) ? env.seq : null
      if (seq && seq > 0) upsertTask({ taskId: id, lastSeq: seq })

      const payload = isRecord(env.data) ? env.data : {}
      const step = taskEventToStep({
        taskId: id,
        seq: seq || 0,
        type: String(env.type || ''),
        data: payload,
        created_at: env.created_at,
      })
      if (step?.id) {
        const seenForTask = (seenStepIdsRef.current[id] ||= {})
        if (seenForTask[step.id]) {
          // For reasoning deltas, append new content to existing title
          let merged = step
          const stepInput = step.input
          if (
            step.toolName === 'reasoning' &&
            isRecord(stepInput) &&
            '_deltaContent' in stepInput
          ) {
            const delta = readString(stepInput, '_deltaContent')
            if (delta) {
              const existing = getTaskSteps(id).find((s) => s.id === step.id)
              const existingTitle = existing?.title || ''
              const prefix = existingTitle.startsWith('原始 Reason: ')
                ? '原始 Reason: '
                : existingTitle.startsWith('事件 Trace: ')
                  ? '事件 Trace: '
                  : ''
              const body = prefix ? existingTitle.slice(prefix.length) : existingTitle
              merged = { ...step, title: prefix + body + delta }
            }
          }
          updateStep(id, step.id, merged)
        } else {
          seenForTask[step.id] = true
          addStep(id, step)
        }
      }

      if (env.type === 'progress') {
        const progress = readNumber(payload, 'progress', NaN)
        const stage =
          readString(payload, 'stage_label').trim() ||
          readString(payload, 'stage').trim()
        if (Number.isFinite(progress)) upsertTask({ taskId: id, progress })
        if (stage) upsertTask({ taskId: id, stage })
        return
      }

      if (env.type === 'item_saved') {
        patchListOnItemSaved(payload.item)
        return
      }

      if (env.type === 'done') {
        const previewId = readStringFrom(payload, ['preview_id', 'previewId']).trim()
        if (previewId) {
          const drafts = normalizeDraftQuestions(payload.draft_questions ?? payload.draftQuestions)
          if (drafts.length > 0) {
            const referenceSource = readString(payload, 'reference_source').trim() || 'any'
            const referenceYearRange = readString(payload, 'reference_year_range').trim() || 'all'
            const useReferenceQuestionsRaw = payload.use_reference_questions
            const count = readNumber(payload, 'count', drafts.length)

            setDraftPreview({
              previewId,
              sessionId: readStringFrom(payload, ['session_id', 'sessionId']).trim(),
              subject: readString(payload, 'subject').trim(),
              topic: readString(payload, 'topic').trim(),
              mode: readString(payload, 'mode').trim() || 'standard',
              useReferenceQuestions: useReferenceQuestionsRaw === undefined ? true : Boolean(useReferenceQuestionsRaw),
              referenceSource,
              referenceYearRange,
              count: Math.max(0, Number.isFinite(count) ? count : drafts.length) || drafts.length,
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
        const msg = readStringFrom(payload, ['error', 'message']).trim() || '任务失败'
        upsertTask({ taskId: id, status: 'failed', error: msg })
        failTask(id, msg)
        return
      }
    },
    [addStep, completeTask, failTask, getTaskSteps, normalizeDraftQuestions, onDone, patchListOnItemSaved, upsertTask, updateStep]
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

  const runMediaImport = useCallback(
    (payload: Omit<ImportMediaQuestionsPayload, 'task_id'> & { task_id?: string }) => {
      const taskId = String(payload.task_id || '').trim() || `ql-media-${generateId()}`
      clearDraftPreview()
      startTask(taskId)
      upsertTask({ taskId, kind: 'media_import', status: 'running', progress: 0, stage: '图片/PDF 录入', lastSeq: 0 })

      importMediaQuestions(
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

      apiClient
        .post('/tasks/question-library/score', { ...payload, task_id: taskId })
        .then(() => {
          streamTask(
            taskId,
            0,
            (evt) => handleEnvelope(taskId, normalizeSseEnvelope(evt)),
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
        })
        .catch((err: unknown) => {
          const message = err instanceof Error ? err.message : readString(err, 'message') || 'score_failed'
          upsertTask({ taskId, status: 'failed', error: message })
          failTask(taskId, message)
        })

      return taskId
    },
    [failTask, getTaskSteps, handleEnvelope, startTask, upsertTask]
  )

  const preferredTask = useMemo(() => {
    const running = tasks.find((t) => t.status === 'running')
    return running || tasks[0] || null
  }, [tasks])

  useEffect(() => {
    if (!restoreLatestPreview || draftPreview || restoreAttemptedRef.current) return
    restoreAttemptedRef.current = true
    let cancelled = false

    ;(async () => {
      try {
        const resp = await getLatestPendingQuestionLibraryPreview()
        if (cancelled || !resp?.preview) return

        const preview: Record<string, unknown> = resp.preview
        const drafts = normalizeDraftQuestions(preview.draft_questions)
        if (drafts.length === 0) return

        const taskId =
          readString(preview, 'task_id').trim() || `ql-preview-${readString(preview, 'preview_id')}`
        const useReferenceQuestionsRaw = preview.use_reference_questions
        const count = readNumber(preview, 'count', drafts.length)

        setDraftPreview({
          previewId: readString(preview, 'preview_id').trim(),
          sessionId: readString(preview, 'session_id').trim(),
          subject: readString(preview, 'subject').trim(),
          topic: readString(preview, 'topic').trim(),
          mode: readString(preview, 'mode').trim() || 'standard',
          useReferenceQuestions: useReferenceQuestionsRaw === undefined ? true : Boolean(useReferenceQuestionsRaw),
          referenceSource: readString(preview, 'reference_source').trim() || 'any',
          referenceYearRange: readString(preview, 'reference_year_range').trim() || 'all',
          count: Math.max(0, Number.isFinite(count) ? count : drafts.length) || drafts.length,
          draftQuestions: drafts,
          taskId,
        })
        upsertTask({ taskId, kind: 'generate', status: 'completed', progress: 92, stage: 'Pending Review', lastSeq: 0 })
      } catch {
        // No pending preview is a normal state; keep the page quiet.
      }
    })()

    return () => {
      cancelled = true
    }
  }, [draftPreview, normalizeDraftQuestions, restoreLatestPreview, upsertTask])

  return {
    tasks,
    preferredTask,
    runCrawl,
    runGenerate,
    runMediaImport,
    runScore,
      draftPreview,
    clearDraftPreview,
    getTaskEvents,
  }
}
