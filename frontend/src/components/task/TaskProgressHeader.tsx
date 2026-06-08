import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { getTask, streamTask, type TaskStreamEvent, type UnifiedTask } from '@/api/tasks'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { cn, formatDuration } from '@/lib/utils'

function formatStatus(status: string): { label: string; tone: 'default' | 'secondary' | 'destructive' } {
  const s = (status || '').toLowerCase()
  if (s === 'running') return { label: '运行中', tone: 'secondary' }
  if (s === 'paused') return { label: '已暂停', tone: 'secondary' }
  if (s === 'completed') return { label: '已完成', tone: 'default' }
  if (s === 'failed') return { label: '失败', tone: 'destructive' }
  if (s === 'canceled' || s === 'cancelled') return { label: '已取消', tone: 'destructive' }
  return { label: status || '未知', tone: 'secondary' }
}

function extractStepTitle(evt: TaskStreamEvent): string | null {
  if (String(evt.type || '') !== 'step') return null
  const data = evt.data ?? {}
  const step = (data as any)?.step
  if (step && typeof step === 'object') {
    const title = String((step as any)?.title || '').trim()
    if (title) return title
  }
  const msg = String((data as any)?.title || (data as any)?.message || '').trim()
  return msg || null
}

export function TaskProgressHeader(props: {
  taskId: string | null | undefined
  className?: string
  compact?: boolean
}) {
  const { taskId, className, compact } = props
  const [lastBeatAt, setLastBeatAt] = useState<number>(Date.now())
  const [lastStepTitle, setLastStepTitle] = useState<string>('')
  const [tick, setTick] = useState(0)
  const lastSeqRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  const { data, isFetching } = useQuery({
    queryKey: ['task', taskId],
    queryFn: () => getTask(String(taskId || '')),
    enabled: Boolean(taskId),
    refetchInterval: (q) => {
      const status = String((q.state.data as any)?.status || '')
      return status === 'running' ? 5000 : false
    },
  })

  const task = data as UnifiedTask | any

  const isRunning = String(task?.status || '').toLowerCase() === 'running'
  useEffect(() => {
    if (!isRunning) return
    const id = window.setInterval(() => setTick((v) => v + 1), 1000)
    return () => window.clearInterval(id)
  }, [isRunning])

  useEffect(() => {
    if (!taskId) return

    if (abortRef.current) abortRef.current.abort()
    abortRef.current = null

    const controller = new AbortController()
    abortRef.current = controller

    const afterSeq = Math.max(0, lastSeqRef.current)

    streamTask(
      String(taskId),
      afterSeq,
      (evt) => {
        lastSeqRef.current = Math.max(lastSeqRef.current, Number(evt.seq || 0))
        setLastBeatAt(Date.now())
        const title = extractStepTitle(evt)
        if (title) setLastStepTitle(title)
      },
      () => {
        // keep last beat timestamp for UI
      },
      undefined,
      { signal: controller.signal }
    )

    return () => {
      controller.abort()
      if (abortRef.current === controller) abortRef.current = null
    }
  }, [taskId])

  const status = useMemo(() => formatStatus(String(task?.status || '')), [task?.status])
  const progress = Math.max(0, Math.min(100, Number(task?.progress || 0)))

  const elapsedMs = useMemo(() => {
    const elapsedS = Number(task?.elapsed_s || 0)
    if (Number.isFinite(elapsedS) && elapsedS > 0) return elapsedS * 1000
    const startedAt = String(task?.started_at || '')
    const ts = startedAt ? Date.parse(startedAt) : NaN
    if (!Number.isFinite(ts)) return null
    return Math.max(0, Date.now() - ts)
  }, [task?.elapsed_s, task?.started_at, tick])

  const etaMs = useMemo(() => {
    const etaS = Number(task?.eta_s || 0)
    if (Number.isFinite(etaS) && etaS > 0) return etaS * 1000
    if (!elapsedMs) return null
    if (progress <= 0.1) return null
    const ratio = 100 / Math.max(1, progress)
    return Math.max(0, elapsedMs * (ratio - 1))
  }, [task?.eta_s, elapsedMs, progress])

  const beatAgoMs = Math.max(0, Date.now() - lastBeatAt)

  if (!taskId) return null

  return (
    <div className={cn('rounded-lg border border-border/60 bg-card px-4 py-3', className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <div className="text-sm font-medium truncate">{String(task?.title || taskId)}</div>
            <Badge variant={status.tone}>{status.label}</Badge>
            {isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          </div>
          {!compact && (
            <div className="mt-1 text-xs text-muted-foreground">
              <span className="mr-3 font-mono">{String(taskId)}</span>
              {lastStepTitle ? <span className="truncate">当前：{lastStepTitle}</span> : <span />}
            </div>
          )}
        </div>
        <div className="text-xs text-muted-foreground tabular-nums text-right">
          {elapsedMs != null && <div>已用 {formatDuration(elapsedMs)}</div>}
          {etaMs != null && etaMs > 0 && <div>预计剩余 {formatDuration(etaMs)}</div>}
          <div>心跳 {formatDuration(beatAgoMs)}</div>
        </div>
      </div>

      <div className="mt-3 space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>进度</span>
          <span>{Math.round(progress)}%</span>
        </div>
        <Progress value={progress} className="h-2" />
      </div>
    </div>
  )
}

