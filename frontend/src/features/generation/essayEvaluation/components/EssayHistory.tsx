import { useQuery } from '@tanstack/react-query'
import { listEssayEvaluations, type EssayEvaluationRecordSummary } from '@/api/essayEvaluations'
import { cn } from '@/lib/utils'
import { formatDate } from '@/lib/utils'

export type EssayHistoryProps = {
  selectedId?: number | null
  onSelect?: (record: EssayEvaluationRecordSummary) => void
  className?: string
}

/**
 * Sidebar list of recent essay evaluations.
 *
 * Polls every 60 seconds; the page is otherwise driven by direct calls into
 * ``listEssayEvaluations`` so the user sees newly-finished evaluations
 * without a manual refresh.
 */
export function EssayHistory({ selectedId, onSelect, className }: EssayHistoryProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['essay-evaluations'],
    queryFn: () => listEssayEvaluations({ limit: 50 }),
    refetchInterval: 60_000,
  })

  return (
    <div className={cn('flex h-full flex-col', className)}>
      <div className="aurora-essay-history-head">
        <div className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground">History stream</div>
        <h3 className="mt-1 text-sm font-semibold">批改历史</h3>
      </div>
      <div className="flex-1 overflow-y-auto">
        {isLoading && <div className="p-3 text-xs text-muted-foreground">加载中…</div>}
        {error && <div className="p-3 text-xs text-rose-600">{(error as Error).message}</div>}
        {!isLoading && !error && (data?.items?.length || 0) === 0 && (
          <div className="p-3 text-xs text-muted-foreground">暂无批改记录</div>
        )}
        <ul>
          {data?.items?.map((item) => {
            const ratio = item.score_max > 0 ? item.score_total / item.score_max : 0
            const isActive = selectedId === item.id
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className={cn(
                    'aurora-essay-history-item block w-full px-3 py-3 text-left transition-colors',
                    isActive && 'is-active',
                  )}
                  onClick={() => onSelect?.(item)}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-sm font-medium">
                      {item.topic || `${item.subject || '语文'} 作文`}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {item.score_total.toFixed(1)}/{item.score_max.toFixed(0)}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span
                      className={cn(
                        'aurora-essay-grade-badge rounded px-1.5',
                        ratio >= 0.85
                          ? 'bg-emerald-100 text-emerald-700'
                          : ratio >= 0.7
                            ? 'bg-blue-100 text-blue-700'
                            : ratio >= 0.55
                              ? 'bg-amber-100 text-amber-700'
                              : 'bg-rose-100 text-rose-700',
                      )}
                    >
                      {item.grade || '—'}
                    </span>
                    <span>{formatDate(item.created_at)}</span>
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
