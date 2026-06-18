import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  getTask,
  listTasks,
  pauseTask,
  resumeTask,
  cancelTask,
  retryTask,
  reviewComposedPaperTask,
  streamTask,
  type TaskStreamEvent,
  type UnifiedTask,
} from '@/api/tasks'
import { taskEventToStep, upsertTaskStep } from '@/components/task/taskEventAdapter'
import { RUNNING_TASKS_REFETCH_INTERVAL_MS } from '@/hooks/useRunningTasks'
import type { TaskStep } from '@/types'
import type {
  ComposeDraft,
  ComposeReviewResult,
  ComposeReviewStatus,
  FormattedStatus,
} from '../types'
import {
  formatStatus,
  getComposeDraft,
  getComposeReviewResult,
} from '../utils'

export type TaskCenterState = {
  // URL params
  selectedTaskId: string
  searchParams: URLSearchParams
  // filters
  statusFilter: string
  typeFilter: string
  timeFilter: string
  query: string
  setQuery: (value: string) => void
  setStatusFilter: (value: string) => void
  setTypeFilter: (value: string) => void
  setTimeFilter: (value: string) => void
  // task list
  tasks: UnifiedTask[]
  filteredTasks: UnifiedTask[]
  taskStats: { label: string; value: string }[]
  typeOptions: string[]
  isFetching: boolean
  refetch: () => void
  taskListRef: React.RefObject<HTMLDivElement | null>
  taskVirtualizer: ReturnType<typeof useVirtualizer>
  selectedTask: UnifiedTask | undefined
  selectedTaskLoading: boolean
  refetchSelectedTask: () => void
  selectedSnapshotStatus: string
  selectedTaskStatus: string
  // compose review
  composeDraft: ComposeDraft | null
  composeReviewResult: ComposeReviewResult | null
  reviewDecisions: Record<string, ComposeReviewStatus>
  setQuestionReviewStatus: (questionId: string, status: ComposeReviewStatus) => void
  isReviewSubmitting: boolean
  reviewError: string | null
  // steps/stream
  steps: TaskStep[]
  streamError: string | null
  // derived
  status: FormattedStatus | null
  canReviewCompose: boolean
  // handlers
  handleSelectTask: (taskId: string) => void
  handlePause: () => Promise<void>
  handleResume: () => Promise<void>
  handleCancel: () => Promise<void>
  handleRetry: () => Promise<void>
  handleComposeReview: () => Promise<void>
}

export function useTaskCenter() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedTaskId = searchParams.get('id') || ''

  const [statusFilter, setStatusFilter] = useState<string>(() => searchParams.get('status') || 'running')
  const [typeFilter, setTypeFilter] = useState<string>(() => searchParams.get('type') || '')
  const [timeFilter, setTimeFilter] = useState<string>(() => searchParams.get('time') || '30d')
  const [query, setQuery] = useState('')

  useEffect(() => {
    setStatusFilter(searchParams.get('status') || 'running')
    setTypeFilter(searchParams.get('type') || '')
    setTimeFilter(searchParams.get('time') || '30d')
  }, [searchParams])

  const { data, refetch, isFetching } = useQuery({
    queryKey: ['tasks', statusFilter, typeFilter],
    queryFn: () =>
      listTasks({
        status: statusFilter === 'all' ? undefined : statusFilter,
        type: typeFilter || undefined,
        limit: 200,
      }),
    refetchInterval: RUNNING_TASKS_REFETCH_INTERVAL_MS,
  })

  const tasks = useMemo(() => data?.tasks || [], [data])
  const taskListRef = useRef<HTMLDivElement | null>(null)

  const {
    data: selectedTaskSnapshot,
    isLoading: selectedTaskLoading,
    refetch: refetchSelectedTask,
  } = useQuery({
    queryKey: ['task', selectedTaskId, 'events'],
    queryFn: () => getTask(selectedTaskId, { includeEvents: true, eventsLimit: 1000 }),
    enabled: Boolean(selectedTaskId),
    refetchInterval: (q) => {
      const status = String(q.state.data?.status || '')
      return status === 'running' ? RUNNING_TASKS_REFETCH_INTERVAL_MS : false
    },
  })

  const typeOptions = useMemo(() => {
    const set = new Set<string>()
    tasks.forEach((t) => {
      const tp = String(t.task_type || '').trim()
      if (tp) set.add(tp)
    })
    return Array.from(set).sort()
  }, [tasks])

  const filteredTasks = useMemo(() => {
    const q = query.trim().toLowerCase()
    const now = Date.now()
    const windowMs =
      timeFilter === '24h'
        ? 24 * 60 * 60 * 1000
        : timeFilter === '7d'
          ? 7 * 24 * 60 * 60 * 1000
          : timeFilter === '30d'
            ? 30 * 24 * 60 * 60 * 1000
            : null

    return tasks.filter((t) => {
      if (q) {
        const ok =
          String(t.title || '').toLowerCase().includes(q) || String(t.id || '').includes(q)
        if (!ok) return false
      }

      if (windowMs != null) {
        const ts = Date.parse(String(t.updated_at || t.created_at || ''))
        if (Number.isFinite(ts) && now - ts > windowMs) return false
      }

      return true
    })
  }, [tasks, query, timeFilter])

  const taskStats = useMemo(() => {
    const counts = {
      running: 0,
      pendingReview: 0,
      failed: 0,
      completed: 0,
    }
    for (const task of tasks) {
      const status = String(task.status || '').toLowerCase()
      if (status === 'running') counts.running += 1
      if (status === 'pending_review') counts.pendingReview += 1
      if (status === 'failed') counts.failed += 1
      if (status === 'completed') counts.completed += 1
    }
    return [
      { label: '运行中', value: `${counts.running}` },
      { label: '待审核', value: `${counts.pendingReview}` },
      { label: '失败', value: `${counts.failed}` },
      { label: '当前列表', value: `${filteredTasks.length}` },
    ]
  }, [filteredTasks.length, tasks])

  const taskVirtualizer = useVirtualizer({
    count: filteredTasks.length,
    getScrollElement: () => taskListRef.current,
    estimateSize: () => 92,
    overscan: 8,
    getItemKey: (index) => String(filteredTasks[index]?.id || index),
  })

  const selectedTask: UnifiedTask | undefined = useMemo(() => {
    if (!selectedTaskId) return undefined
    return (
      selectedTaskSnapshot ||
      filteredTasks.find((t) => String(t.id) === selectedTaskId) ||
      tasks.find((t) => String(t.id) === selectedTaskId)
    )
  }, [selectedTaskId, selectedTaskSnapshot, filteredTasks, tasks])

  const composeDraft = useMemo(() => getComposeDraft(selectedTask), [selectedTask])
  const composeReviewResult = useMemo(() => getComposeReviewResult(selectedTask), [selectedTask])
  const composeDraftQuestionKey = useMemo(
    () => (composeDraft?.questions || []).map((question) => question.questionId).join('|'),
    [composeDraft]
  )
  const selectedSnapshotStatus = String(selectedTaskSnapshot?.status || '')
  const selectedTaskStatus = String(selectedTask?.status || '')

  const [steps, setSteps] = useState<TaskStep[]>([])
  const [streamError, setStreamError] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [isReviewSubmitting, setIsReviewSubmitting] = useState(false)
  const [reviewDecisions, setReviewDecisions] = useState<Record<string, ComposeReviewStatus>>({})
  const lastSeqRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    setSteps([])
    setStreamError(null)
    setReviewError(null)
    lastSeqRef.current = 0

    if (abortRef.current) abortRef.current.abort()
    abortRef.current = null

    if (!selectedTaskId) return
  }, [selectedTaskId])

  useEffect(() => {
    setReviewDecisions({})
  }, [selectedTaskId, composeDraftQuestionKey])

  useEffect(() => {
    if (!selectedTaskId || !selectedTaskSnapshot) return

    const events = Array.isArray(selectedTaskSnapshot.events) ? selectedTaskSnapshot.events : []
    let snapshotSteps: TaskStep[] = []
    for (const evt of events) {
      const step = taskEventToStep(evt)
      if (step) snapshotSteps = upsertTaskStep(snapshotSteps, step)
    }
    setSteps((prev) => snapshotSteps.reduce((merged, step) => upsertTaskStep(merged, step), prev))
    setStreamError(null)
    lastSeqRef.current = Math.max(lastSeqRef.current, Number(selectedTaskSnapshot.last_seq || 0))
  }, [selectedTaskId, selectedTaskSnapshot])

  useEffect(() => {
    if (!selectedTaskId || selectedTaskLoading) return

    const status = String(selectedSnapshotStatus || selectedTaskStatus).toLowerCase()
    if (status && status !== 'running') return

    if (abortRef.current) abortRef.current.abort()

    const controller = new AbortController()
    abortRef.current = controller
    const afterSeq = Math.max(0, Number(lastSeqRef.current || 0))
    lastSeqRef.current = afterSeq

    streamTask(
      selectedTaskId,
      afterSeq,
      (evt) => {
        lastSeqRef.current = Math.max(lastSeqRef.current, Number(evt.seq || 0))
        const step = taskEventToStep(evt as TaskStreamEvent)
        if (!step) return
        setSteps((prev) => upsertTaskStep(prev, step))
      },
      (err) => setStreamError(err.message || 'stream_error'),
      undefined,
      { signal: controller.signal }
    )

    return () => {
      controller.abort()
      if (abortRef.current === controller) abortRef.current = null
    }
  }, [selectedSnapshotStatus, selectedTaskId, selectedTaskLoading, selectedTaskStatus])

  const setUrlParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    if (!value) next.delete(key)
    else next.set(key, value)
    setSearchParams(next, { replace: true })
  }

  const handleSelectTask = (taskId: string) => {
    setUrlParam('id', taskId)
  }

  const handlePause = async () => {
    if (!selectedTaskId) return
    await pauseTask(selectedTaskId)
    refetch()
    refetchSelectedTask()
  }

  const handleResume = async () => {
    if (!selectedTaskId) return
    await resumeTask(selectedTaskId)
    refetch()
    refetchSelectedTask()
  }

  const handleCancel = async () => {
    if (!selectedTaskId) return
    await cancelTask(selectedTaskId)
    refetch()
    refetchSelectedTask()
  }

  const handleRetry = async () => {
    if (!selectedTaskId) return
    const res = await retryTask(selectedTaskId)
    if (res.taskId) {
      setUrlParam('id', res.taskId)
    }
    refetch()
    refetchSelectedTask()
  }

  const handleComposeReview = async () => {
    if (!selectedTaskId || isReviewSubmitting) return
    const payload = composeDraft
      ? {
          questions: composeDraft.questions.map((question) => ({
            questionId: question.questionId,
            status: reviewDecisions[question.questionId] || 'approved',
          })),
        }
      : undefined
    setIsReviewSubmitting(true)
    setReviewError(null)
    try {
      await reviewComposedPaperTask(selectedTaskId, payload)
      await Promise.all([refetch(), refetchSelectedTask()])
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err || '')
      setReviewError(msg || 'compose_review_failed')
    } finally {
      setIsReviewSubmitting(false)
    }
  }

  const status = selectedTask ? formatStatus(String(selectedTask.status || '')) : null
  const canReviewCompose =
    String(selectedTask?.task_type || '') === 'paper_compose' && String(selectedTask?.status || '') === 'pending_review'

  const setQuestionReviewStatus = (questionId: string, reviewStatus: ComposeReviewStatus) => {
    const qid = String(questionId || '').trim()
    if (!qid) return
    setReviewDecisions((prev) => ({ ...prev, [qid]: reviewStatus }))
  }

  const setUrlParamForFilter = (key: string, value: string) => {
    setUrlParam(key, value)
    if (key === 'status') setStatusFilter(value)
    if (key === 'type') setTypeFilter(value)
    if (key === 'time') setTimeFilter(value)
  }

  return {
    selectedTaskId,
    searchParams,
    statusFilter,
    typeFilter,
    timeFilter,
    query,
    setQuery,
    setStatusFilter: (value: string) => setUrlParamForFilter('status', value),
    setTypeFilter: (value: string) => setUrlParamForFilter('type', value),
    setTimeFilter: (value: string) => setUrlParamForFilter('time', value),
    tasks,
    filteredTasks,
    taskStats,
    typeOptions,
    isFetching,
    refetch,
    taskListRef,
    taskVirtualizer,
    selectedTask,
    selectedTaskLoading,
    refetchSelectedTask,
    selectedSnapshotStatus,
    selectedTaskStatus,
    composeDraft,
    composeReviewResult,
    reviewDecisions,
    setQuestionReviewStatus,
    isReviewSubmitting,
    reviewError,
    steps,
    streamError,
    status,
    canReviewCompose,
    handleSelectTask,
    handlePause,
    handleResume,
    handleCancel,
    handleRetry,
    handleComposeReview,
  }
}
