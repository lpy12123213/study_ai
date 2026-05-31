import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Clock3, RefreshCw } from 'lucide-react'
import { getLlmDebugCalls, type LlmDebugCall } from '@/api/llmDebug'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { DEFAULT_RESOURCE_REFETCH_INTERVAL_MS } from '@/hooks/useRunningTasks'
import { cn } from '@/lib/utils'

type Props = {
  isActive: boolean
}

function formatNumber(value: unknown): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '0'
  return new Intl.NumberFormat('zh-CN').format(Math.round(numeric))
}

function formatCost(value: unknown): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return '$0'
  return `$${numeric.toFixed(numeric < 0.01 ? 6 : 4)}`
}

function formatTime(tsS: unknown): string {
  const numeric = Number(tsS)
  if (!Number.isFinite(numeric) || numeric <= 0) return '--'
  return new Date(numeric * 1000).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function statusTone(status: string): 'default' | 'secondary' | 'destructive' {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'ok') return 'default'
  if (normalized === 'unknown') return 'secondary'
  return 'destructive'
}

function CallRow({ call }: { call: LlmDebugCall }) {
  return (
    <div className="grid gap-3 rounded-lg border bg-card p-4 md:grid-cols-[1fr_auto]">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={statusTone(call.status)}>{call.status || 'unknown'}</Badge>
          <span className="truncate font-mono text-sm">{call.provider}:{call.model}</span>
          {call.stream ? <Badge variant="outline">stream</Badge> : null}
        </div>
        <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
          <span className="truncate">request_id: {call.request_id || '--'}</span>
          <span>finish: {call.finish_reason || '--'}</span>
          <span>tokens: {formatNumber(call.usage?.total_tokens)}</span>
          <span>cached: {formatNumber(call.usage?.cached_tokens || 0)}</span>
        </div>
      </div>
      <div className="flex items-center gap-2 text-sm text-muted-foreground md:justify-end">
        <Clock3 className="h-4 w-4" />
        <span>{formatTime(call.ts_s)}</span>
        <span>{call.elapsed_s == null ? '--' : `${Number(call.elapsed_s).toFixed(2)}s`}</span>
      </div>
    </div>
  )
}

export function LlmDebugPanel({ isActive }: Props) {
  const query = useQuery({
    queryKey: ['llm-debug', 20],
    queryFn: () => getLlmDebugCalls({ limit: 20 }),
    enabled: isActive,
    refetchInterval: DEFAULT_RESOURCE_REFETCH_INTERVAL_MS,
  })

  const payload = query.data
  const modelRows = useMemo(() => {
    const entries = Object.entries(payload?.by_model || {})
    const maxTokens = Math.max(1, ...entries.map(([, item]) => Number(item.total_tokens || 0)))
    return entries
      .sort((a, b) => Number(b[1].total_tokens || 0) - Number(a[1].total_tokens || 0))
      .slice(0, 8)
      .map(([key, item]) => ({
        key,
        requests: Number(item.requests || 0),
        totalTokens: Number(item.total_tokens || 0),
        cachedTokens: Number(item.cached_tokens || 0),
        costUsd: Number(item.cost_usd || 0),
        pct: Math.max(4, Math.round((Number(item.total_tokens || 0) / maxTokens) * 100)),
      }))
  }, [payload?.by_model])

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium">LLM 调试</h2>
          <p className="text-sm text-muted-foreground">最近 {payload?.count ?? 0} 次调用</p>
        </div>
        <Button variant="outline" onClick={() => void query.refetch()} disabled={query.isFetching}>
          <RefreshCw className={cn('h-4 w-4', query.isFetching && 'animate-spin')} />
          <span className="ml-2">刷新</span>
        </Button>
      </div>

      <Separator />

      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-lg border bg-card p-4">
          <div className="text-xs text-muted-foreground">请求</div>
          <div className="mt-1 text-2xl font-semibold">{formatNumber(payload?.count || 0)}</div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-xs text-muted-foreground">总 tokens</div>
          <div className="mt-1 text-2xl font-semibold">{formatNumber(payload?.totals?.total_tokens)}</div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-xs text-muted-foreground">缓存 tokens</div>
          <div className="mt-1 text-2xl font-semibold">{formatNumber(payload?.totals?.cached_tokens || 0)}</div>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="text-xs text-muted-foreground">成本</div>
          <div className="mt-1 text-2xl font-semibold">{formatCost(payload?.totals?.cost_usd)}</div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Activity className="h-4 w-4" />
          模型消耗
        </div>
        {modelRows.length === 0 ? (
          <div className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">
            暂无调用记录
          </div>
        ) : (
          modelRows.map((row) => (
            <div key={row.key} className="rounded-lg border bg-card p-4">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate font-mono">{row.key}</span>
                <span className="text-muted-foreground">{formatNumber(row.totalTokens)} tokens</span>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary" style={{ width: `${row.pct}%` }} />
              </div>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
                <span>{row.requests} calls</span>
                <span>cached {formatNumber(row.cachedTokens)}</span>
                <span>{formatCost(row.costUsd)}</span>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="space-y-3">
        <div className="text-sm font-medium">最近调用</div>
        {query.isError ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
            读取失败
          </div>
        ) : null}
        {(payload?.calls || []).map((call) => (
          <CallRow key={`${call.request_id}-${call.ts_s}`} call={call} />
        ))}
        {!query.isFetching && (payload?.calls || []).length === 0 ? (
          <div className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">
            暂无调用记录
          </div>
        ) : null}
      </div>
    </div>
  )
}
