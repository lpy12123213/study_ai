import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useSearchParams } from 'react-router-dom'
import { Pause, Play, RefreshCcw, Loader2, ListChecks, XCircle, Ban, RotateCcw, ClipboardCheck, Sparkles } from 'lucide-react'
import { getTask, listTasks, pauseTask, resumeTask, cancelTask, retryTask, reviewComposedPaperTask, streamTask, type TaskStreamEvent, type UnifiedTask } from '@/api/tasks'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { taskEventToStep, upsertTaskStep } from '@/components/task/taskEventAdapter'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { RUNNING_TASKS_REFETCH_INTERVAL_MS } from '@/hooks/useRunningTasks'
import type { TaskStep } from '@/types'

type ComposeReviewStatus = 'approved' | 'rejected'

type ComposeDraftQuestion = {
  questionId: string
  stem: string
  type: string
  difficulty: string
}

type ComposeDraft = {
  paperName: string
  questions: ComposeDraftQuestion[]
}

type ComposeReviewResult = {
  paperId: string
  name: string
  questionCount: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object')
}

function readString(record: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string') return value.trim()
    if (typeof value === 'number') return String(value)
  }
  return ''
}

function parseComposeDraft(value: unknown): ComposeDraft | null {
  if (!isRecord(value)) return null
  const rawQuestions = Array.isArray(value.questions) ? value.questions : []
  const questions = rawQuestions
    .filter(isRecord)
    .map((item) => ({
      questionId: readString(item, 'questionId', 'question_id'),
      stem: readString(item, 'stem'),
      type: readString(item, 'type', 'questionType', 'question_type'),
      difficulty: readString(item, 'difficulty'),
    }))
    .filter((item) => item.questionId)
  if (questions.length === 0) return null
  return {
    paperName: readString(value, 'paperName', 'paper_name'),
    questions,
  }
}

function getComposeDraft(task: UnifiedTask | undefined): ComposeDraft | null {
  const rawResult = task?.result
  const result: Record<string, unknown> | null = isRecord(rawResult) ? rawResult : null
  const resultDraft = parseComposeDraft(result?.composeDraft)
  if (resultDraft) return resultDraft

  const events = Array.isArray(task?.events) ? task.events : []
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const rawData = events[index]?.data
    const data: Record<string, unknown> | null = isRecord(rawData) ? rawData : null
    const eventDraft = parseComposeDraft(data?.composeDraft || data?.compose_draft)
    if (eventDraft) return eventDraft
  }
  return null
}

function getComposeReviewResult(task: UnifiedTask | undefined): ComposeReviewResult | null {
  if (String(task?.task_type || '') !== 'paper_compose') return null
  if (String(task?.status || '').toLowerCase() !== 'completed') return null

  const result = isRecord(task?.result) ? task.result : null
  if (!result) return null

  const paperId = readString(result, 'id', 'paperId', 'paper_id')
  const name = readString(result, 'name', 'paperName', 'paper_name', 'title')
  const rawQuestions = Array.isArray(result.questions) ? result.questions : []
  const questionCount = rawQuestions.length || Number(result.question_count || result.questionCount || 0)

  if (!paperId && !name && !questionCount) return null
  return {
    paperId,
    name: name || '已保存试卷',
    questionCount: Number.isFinite(questionCount) ? Number(questionCount) : 0,
  }
}

function formatStatus(status: string): { label: string; tone: 'default' | 'secondary' | 'destructive' } {
  const s = (status || '').toLowerCase()
  if (s === 'running') return { label: '运行中', tone: 'secondary' }
  if (s === 'paused') return { label: '已暂停', tone: 'secondary' }
  if (s === 'pending_review') return { label: '待审核', tone: 'secondary' }
  if (s === 'completed') return { label: '已完成', tone: 'default' }
  if (s === 'failed') return { label: '失败', tone: 'destructive' }
  if (s === 'canceled' || s === 'cancelled') return { label: '已取消', tone: 'destructive' }
  return { label: status || '未知', tone: 'secondary' }
}

export default function TaskCenterPage() {
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
    } catch (err: any) {
      setReviewError(err?.message || 'compose_review_failed')
    } finally {
      setIsReviewSubmitting(false)
    }
  }

  const status = selectedTask ? formatStatus(String(selectedTask.status || '')) : null
  const canReviewCompose =
    String(selectedTask?.task_type || '') === 'paper_compose' && String(selectedTask?.status || '') === 'pending_review'

  const setQuestionReviewStatus = (questionId: string, status: ComposeReviewStatus) => {
    const qid = String(questionId || '').trim()
    if (!qid) return
    setReviewDecisions((prev) => ({ ...prev, [qid]: status }))
  }

  return (
    <div className="aurora-task-screen h-full flex flex-col min-h-0">
      <div className="aurora-task-hero p-4 flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="aurora-kicker">
            <Sparkles className="h-3.5 w-3.5" />
            Task Queue Control Tower
          </div>
          <div className="mt-2 flex items-center gap-2">
            <ListChecks className="h-5 w-5 text-primary" />
            <div className="font-semibold">任务中心</div>
            {isFetching && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">监控生成、导出、组卷和审核任务，支持暂停、恢复、取消、重试与人工审核。</p>
        </div>

        <div className="aurora-task-stat-grid">
          {taskStats.map((item) => (
            <div key={item.label} className="aurora-task-stat">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>

        <div className="aurora-task-actions flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCcw className="h-4 w-4 mr-2" />
            刷新
          </Button>
        </div>
      </div>

      <div className="aurora-task-body flex-1 flex overflow-hidden min-h-0">
        {/* Left: task list */}
        <div className="aurora-task-list w-full md:w-[360px] md:max-w-[45%] shrink-0 flex flex-col min-h-0">
          <div className="aurora-task-filter-panel p-3 space-y-2">
            <Input className="aurora-task-input" placeholder="搜索任务标题/ID…" value={query} onChange={(e) => setQuery(e.target.value)} />

            <div className="flex items-center gap-2">
              <select
                className="aurora-task-select h-9 rounded-md border px-2 text-sm flex-1"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value)
                  setUrlParam('status', e.target.value)
                }}
              >
                <option value="running">运行中</option>
                <option value="paused">已暂停</option>
                <option value="pending_review">待审核</option>
                <option value="failed">失败</option>
                <option value="completed">已完成</option>
                <option value="all">全部</option>
              </select>

              <select
                className="aurora-task-select h-9 rounded-md border px-2 text-sm flex-1"
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value)
                  setUrlParam('type', e.target.value)
                }}
              >
                <option value="">全部类型</option>
                {typeOptions.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            <select
              className="aurora-task-select h-9 rounded-md border px-2 text-sm w-full"
              value={timeFilter}
              onChange={(e) => {
                setTimeFilter(e.target.value)
                setUrlParam('time', e.target.value)
              }}
            >
              <option value="24h">最近 24 小时</option>
              <option value="7d">最近 7 天</option>
              <option value="30d">最近 30 天</option>
              <option value="all">不限时间</option>
            </select>
          </div>

          <div ref={taskListRef} className="flex-1 overflow-auto">
            <div className="relative p-2" style={{ height: filteredTasks.length > 0 ? taskVirtualizer.getTotalSize() + 16 : '100%' }}>
              {taskVirtualizer.getVirtualItems().map((virtualItem) => {
                const t = filteredTasks[virtualItem.index]
                if (!t) return null
                const tid = String(t.id)
                const active = tid === selectedTaskId
                const s = formatStatus(String(t.status || ''))
                const progress = Number(t.progress || 0)
                const eta = Number(t.eta_s || 0)

                return (
                  <div
                    key={virtualItem.key}
                    data-index={virtualItem.index}
                    ref={taskVirtualizer.measureElement}
                    className="absolute left-2 right-2"
                    style={{ transform: `translateY(${virtualItem.start}px)` }}
                  >
                    <button
                      type="button"
                      onClick={() => handleSelectTask(tid)}
                      className={cn(
                        'aurora-task-item w-full text-left rounded-md px-3 py-2 transition-colors',
                        active && 'is-active'
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-sm font-medium truncate">{String(t.title || tid)}</div>
                          <div className="text-xs text-muted-foreground truncate">{tid}</div>
                        </div>
                        <Badge variant={s.tone}>{s.label}</Badge>
                      </div>
                      <div className="mt-2">
                        <Progress value={progress} className="h-1.5" />
                        <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
                          <span>{Math.round(progress)}%</span>
                          {eta > 0 ? <span>预计剩余 {Math.ceil(eta)}s</span> : <span />}
                        </div>
                      </div>
                    </button>
                  </div>
                )
              })}

              {filteredTasks.length === 0 && (
                <div className="text-sm text-muted-foreground text-center py-10">暂无任务</div>
              )}
            </div>
          </div>
        </div>

        {/* Right: details */}
        <div className="aurora-task-detail flex-1 min-w-0 flex flex-col overflow-hidden min-h-0">
          {!selectedTask ? (
            <div className="aurora-task-empty flex-1 flex items-center justify-center text-muted-foreground">
              <div className="text-center">
                <div className="mx-auto mb-4 h-14 w-14 rounded-2xl border border-border/70 bg-background/70" />
                <div className="font-medium text-foreground">选择任务查看详情</div>
                <p className="mt-2 text-xs text-muted-foreground">任务时间线、审核草稿和控制操作会显示在这里。</p>
              </div>
            </div>
          ) : (
            <>
              <div className="aurora-task-detail-head p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-base font-semibold truncate">{selectedTask.title}</div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      <span className="mr-2">ID: {selectedTask.id}</span>
                      <span className="mr-2">类型: {selectedTask.task_type}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {status && <Badge variant={status.tone}>{status.label}</Badge>}
                    {String(selectedTask.status) === 'running' && (
                      <>
                        <Button size="sm" variant="outline" onClick={handlePause}>
                          <Pause className="h-4 w-4 mr-2" />
                          暂停
                        </Button>
                        <Button size="sm" variant="destructive" onClick={handleCancel}>
                          <Ban className="h-4 w-4 mr-2" />
                          取消
                        </Button>
                      </>
                    )}
                    {String(selectedTask.status) === 'paused' && (
                      <>
                        <Button size="sm" onClick={handleResume}>
                          <Play className="h-4 w-4 mr-2" />
                          恢复
                        </Button>
                        <Button size="sm" variant="destructive" onClick={handleCancel}>
                          <Ban className="h-4 w-4 mr-2" />
                          取消
                        </Button>
                      </>
                    )}
                    {canReviewCompose && (
                      <Button size="sm" onClick={handleComposeReview} disabled={isReviewSubmitting}>
                        {isReviewSubmitting ? (
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        ) : (
                          <ClipboardCheck className="h-4 w-4 mr-2" />
                        )}
                        提交人工审核
                      </Button>
                    )}
                    {['completed', 'failed', 'canceled', 'cancelled'].includes(String(selectedTask.status)) && (
                      <Button size="sm" variant="secondary" onClick={handleRetry}>
                        <RotateCcw className="h-4 w-4 mr-2" />
                        重试
                      </Button>
                    )}
                  </div>
                </div>

                <div className="aurora-task-progress mt-3 space-y-1.5">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>进度</span>
                    <span>{Math.round(Number(selectedTask.progress || 0))}%</span>
                  </div>
                  <Progress value={Number(selectedTask.progress || 0)} className="h-2" />
                  {reviewError && (
                    <div className="aurora-task-inline-error mt-2 text-xs text-destructive">{reviewError}</div>
                  )}
                </div>
              </div>

              <div className="flex-1 overflow-hidden min-h-0">
                <ScrollArea className="h-full">
                  <div className="p-4">
                    {streamError && (
                      <div className="aurora-task-stream-error mb-4 rounded-lg p-3 text-sm flex items-start gap-2">
                        <XCircle className="h-4 w-4 text-destructive mt-0.5" />
                        <div>
                          <div className="font-medium text-destructive">事件流断开</div>
                          <div className="text-muted-foreground">{streamError}</div>
                        </div>
                      </div>
                    )}
                    {composeReviewResult && (
                      <div className="aurora-task-review-card mb-4 rounded-lg p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 text-sm font-medium">
                              <ClipboardCheck className="h-4 w-4 text-primary" />
                              <span>试卷已保存</span>
                            </div>
                            <div className="mt-1 truncate text-sm">{composeReviewResult.name}</div>
                            <div className="mt-0.5 text-xs text-muted-foreground">
                              {composeReviewResult.paperId ? `ID: ${composeReviewResult.paperId}` : '本地试卷'}
                              {composeReviewResult.questionCount > 0 ? ` · ${composeReviewResult.questionCount} 题` : ''}
                            </div>
                          </div>
                          <Badge variant="default">已完成</Badge>
                        </div>
                      </div>
                    )}
                    {canReviewCompose && composeDraft && (
                      <div className="aurora-task-review-card mb-4 rounded-lg p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-medium">人工审核草稿</div>
                            <div className="mt-0.5 text-xs text-muted-foreground">
                              {composeDraft.paperName || selectedTask.title} · {composeDraft.questions.length} 题
                            </div>
                          </div>
                          <Badge variant="secondary">待审核</Badge>
                        </div>

                        <div className="mt-3 space-y-2">
                          {composeDraft.questions.map((question, index) => {
                            const decision = reviewDecisions[question.questionId] || 'approved'
                            return (
                              <div key={question.questionId} className="aurora-task-review-question rounded-md p-3">
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <div className="text-xs text-muted-foreground">
                                      #{index + 1} {question.type || '题目'} {question.difficulty ? ` · ${question.difficulty}` : ''}
                                    </div>
                                    <div className="mt-1 line-clamp-3 text-sm">{question.stem || question.questionId}</div>
                                  </div>
                                  <div className="flex shrink-0 items-center gap-2">
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant={decision === 'approved' ? 'secondary' : 'outline'}
                                      onClick={() => setQuestionReviewStatus(question.questionId, 'approved')}
                                      aria-label={`保留 ${question.questionId}`}
                                    >
                                      保留
                                    </Button>
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant={decision === 'rejected' ? 'destructive' : 'outline'}
                                      onClick={() => setQuestionReviewStatus(question.questionId, 'rejected')}
                                      aria-label={`剔除 ${question.questionId}`}
                                    >
                                      剔除
                                    </Button>
                                  </div>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                    <TaskTimeline steps={steps} />
                  </div>
                </ScrollArea>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
