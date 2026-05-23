import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useSearchParams } from 'react-router-dom'
import { Pause, Play, RefreshCcw, Loader2, ListChecks, XCircle, Ban, RotateCcw } from 'lucide-react'
import { getTask, listTasks, pauseTask, resumeTask, cancelTask, retryTask, streamTask, type TaskStreamEvent, type UnifiedTask } from '@/api/tasks'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { taskEventToStep, upsertTaskStep } from '@/components/task/taskEventAdapter'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { TaskStep } from '@/types'

function formatStatus(status: string): { label: string; tone: 'default' | 'secondary' | 'destructive' } {
  const s = (status || '').toLowerCase()
  if (s === 'running') return { label: '运行中', tone: 'secondary' }
  if (s === 'paused') return { label: '已暂停', tone: 'secondary' }
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

  const { data, refetch, isFetching } = useQuery({
    queryKey: ['tasks', statusFilter, typeFilter],
    queryFn: () =>
      listTasks({
        status: statusFilter === 'all' ? undefined : statusFilter,
        type: typeFilter || undefined,
        limit: 200,
      }),
    refetchInterval: 5000,
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
      return status === 'running' ? 5000 : false
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
  const selectedSnapshotLastSeq = Number(selectedTaskSnapshot?.last_seq || 0)
  const selectedSnapshotStatus = String(selectedTaskSnapshot?.status || '')
  const selectedTaskStatus = String(selectedTask?.status || '')

  const [steps, setSteps] = useState<TaskStep[]>([])
  const [streamError, setStreamError] = useState<string | null>(null)
  const lastSeqRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    setSteps([])
    setStreamError(null)
    lastSeqRef.current = 0

    if (abortRef.current) abortRef.current.abort()
    abortRef.current = null

    if (!selectedTaskId) return
  }, [selectedTaskId])

  useEffect(() => {
    if (!selectedTaskId || !selectedTaskSnapshot) return

    const events = Array.isArray(selectedTaskSnapshot.events) ? selectedTaskSnapshot.events : []
    let nextSteps: TaskStep[] = []
    for (const evt of events) {
      const step = taskEventToStep(evt)
      if (step) nextSteps = upsertTaskStep(nextSteps, step)
    }
    setSteps(nextSteps)
    setStreamError(null)
    lastSeqRef.current = Math.max(0, Number(selectedTaskSnapshot.last_seq || 0))
  }, [selectedTaskId, selectedTaskSnapshot])

  useEffect(() => {
    if (!selectedTaskId || selectedTaskLoading) return

    const status = String(selectedSnapshotStatus || selectedTaskStatus).toLowerCase()
    if (status && status !== 'running') return

    if (abortRef.current) abortRef.current.abort()

    const controller = new AbortController()
    abortRef.current = controller
    const afterSeq = Math.max(0, Number(selectedSnapshotLastSeq || lastSeqRef.current || 0))
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

    return () => controller.abort()
  }, [selectedSnapshotLastSeq, selectedSnapshotStatus, selectedTaskId, selectedTaskLoading, selectedTaskStatus])

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

  const status = selectedTask ? formatStatus(String(selectedTask.status || '')) : null

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="p-4 border-b border-border flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ListChecks className="h-5 w-5 text-primary" />
          <div className="font-semibold">任务中心</div>
          {isFetching && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCcw className="h-4 w-4 mr-2" />
            刷新
          </Button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Left: task list */}
        <div className="w-[360px] max-w-[45%] shrink-0 border-r border-border flex flex-col min-h-0">
          <div className="p-3 space-y-2 border-b border-border">
            <Input placeholder="搜索任务标题/ID…" value={query} onChange={(e) => setQuery(e.target.value)} />

            <div className="flex items-center gap-2">
              <select
                className="h-9 rounded-md border border-input bg-background px-2 text-sm flex-1"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value)
                  setUrlParam('status', e.target.value)
                }}
              >
                <option value="running">运行中</option>
                <option value="paused">已暂停</option>
                <option value="failed">失败</option>
                <option value="completed">已完成</option>
                <option value="all">全部</option>
              </select>

              <select
                className="h-9 rounded-md border border-input bg-background px-2 text-sm flex-1"
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
              className="h-9 rounded-md border border-input bg-background px-2 text-sm w-full"
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
                        'w-full text-left rounded-md border border-border/60 px-3 py-2 hover:bg-accent/30 transition-colors',
                        active && 'bg-accent/50 border-border'
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
        <div className="flex-1 min-w-0 flex flex-col overflow-hidden min-h-0">
          {!selectedTask ? (
            <div className="flex-1 flex items-center justify-center text-muted-foreground">
              选择左侧任务查看详情
            </div>
          ) : (
            <>
              <div className="p-4 border-b border-border">
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
                    {['completed', 'failed', 'canceled', 'cancelled'].includes(String(selectedTask.status)) && (
                      <Button size="sm" variant="secondary" onClick={handleRetry}>
                        <RotateCcw className="h-4 w-4 mr-2" />
                        重试
                      </Button>
                    )}
                  </div>
                </div>

                <div className="mt-3 space-y-1.5">
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>进度</span>
                    <span>{Math.round(Number(selectedTask.progress || 0))}%</span>
                  </div>
                  <Progress value={Number(selectedTask.progress || 0)} className="h-2" />
                </div>
              </div>

              <div className="flex-1 overflow-hidden min-h-0">
                <ScrollArea className="h-full">
                  <div className="p-4">
                    {streamError && (
                      <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm flex items-start gap-2">
                        <XCircle className="h-4 w-4 text-destructive mt-0.5" />
                        <div>
                          <div className="font-medium text-destructive">事件流断开</div>
                          <div className="text-muted-foreground">{streamError}</div>
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
