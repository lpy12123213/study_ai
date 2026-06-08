import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Circle, ListTodo, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import * as learningPlansApi from '@/api/learningPlans'
import { cn } from '@/lib/utils'

export default function LearningPlansTodoPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const planIdParam = String(searchParams.get('planId') || '').trim()
  const planId = planIdParam ? Number(planIdParam) : null
  const [pendingItemIds, setPendingItemIds] = useState<Record<number, boolean>>({})
  const [mutationError, setMutationError] = useState<string | null>(null)

  const { data: plans = [], isLoading, error } = useQuery({
    queryKey: ['learningPlans'],
    queryFn: () => learningPlansApi.listLearningPlans({ include_archived: false, limit: 50 }),
  })

  const fallbackPlanId = planId || plans[0]?.id || null

  const { data: planDetail, isFetching: isLoadingPlanDetail } = useQuery({
    queryKey: ['learningPlan', fallbackPlanId],
    queryFn: () => learningPlansApi.getLearningPlan(fallbackPlanId!),
    enabled: Boolean(fallbackPlanId),
  })

  const activePlan = planDetail || (fallbackPlanId ? plans.find((p) => p.id === fallbackPlanId) : null) || null

  const setCompleted = useMutation({
    mutationFn: (input: { itemId: number; completed: boolean }) =>
      learningPlansApi.setLearningPlanItemCompleted(input.itemId, input.completed),
    onMutate: (input) => {
      setMutationError(null)
      setPendingItemIds((prev) => ({ ...prev, [input.itemId]: true }))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['learningPlans'] })
      if (activePlan?.id) queryClient.invalidateQueries({ queryKey: ['learningPlan', activePlan.id] })
    },
    onError: (err: any) => {
      setMutationError(err?.message || '更新待办状态失败')
    },
    onSettled: (_data, _error, input) => {
      if (!input) return
      setPendingItemIds((prev) => {
        const next = { ...prev }
        delete next[input.itemId]
        return next
      })
    },
  })

  const items = useMemo(() => {
    const list = activePlan?.items || []
    return [...list].sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0))
  }, [activePlan])

  const completedCount = items.filter((x) => x.completed).length
  const allDone = items.length > 0 && completedCount === items.length

  return (
    <div className="h-full flex flex-col overflow-hidden bg-background">
      <div className="border-b border-border p-4 flex items-center justify-between sticky top-0 bg-background/80 backdrop-blur-sm z-10">
        <div className="flex items-center gap-2 font-semibold">
          <ListTodo className="h-4 w-4 text-primary" />
          学习计划
        </div>
      </div>

      <div className="flex-1 min-h-0 flex flex-col lg:flex-row overflow-hidden">
        <aside className="w-full lg:w-80 border-b lg:border-b-0 lg:border-r border-border bg-muted/20 p-4 overflow-auto">
          <div className="text-sm font-medium mb-3">我的计划</div>
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          )}
          {Boolean(error) && <ErrorNotice error={error} />}
          {!isLoading && !error && plans.length === 0 && (
            <div className="text-sm text-muted-foreground">暂无学习计划。可从资料详情页一键生成。</div>
          )}

          <div className="space-y-2">
            {plans.map((p) => (
              <button
                key={p.id}
                type="button"
                className={cn(
                  'w-full text-left rounded-md border px-3 py-2 bg-background hover:bg-accent transition-colors',
                  String(activePlan?.id) === String(p.id) && 'border-primary/50 ring-2 ring-primary/10'
                )}
                onClick={() => navigate(`/learning-plans?planId=${p.id}`)}
              >
                <div className="font-medium text-sm truncate">{p.title}</div>
                <div className="text-xs text-muted-foreground mt-1">#{p.id}</div>
              </button>
            ))}
          </div>
        </aside>

        <main className="flex-1 min-h-0 overflow-hidden">
          <ScrollArea className="h-full">
            <div className="max-w-3xl mx-auto p-6 space-y-4">
              {!activePlan ? (
                <Card className="p-6">
                  <div className="text-sm text-muted-foreground">请选择一个学习计划。</div>
                </Card>
              ) : (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-lg font-semibold truncate">{activePlan.title}</div>
                      <div className="text-xs text-muted-foreground mt-1">
                        完成 {completedCount}/{items.length}
                      </div>
                    </div>
                    {isLoadingPlanDetail && (
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        更新中…
                      </div>
                    )}
                  </div>

                  {allDone && (
                    <Card className="p-4 bg-primary/5 border-primary/20">
                      <div className="font-medium text-sm">全部完成</div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        下一步建议：回看错题本、补齐未解决批注，并从新知识点生成练习卷。
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button type="button" variant="outline" size="sm" onClick={() => navigate('/wrongbook')}>
                          打开错题本
                        </Button>
                        <Button type="button" variant="outline" size="sm" onClick={() => navigate('/annotations?tag=未解决')}>
                          查看未解决批注
                        </Button>
                      </div>
                    </Card>
                  )}

                  {mutationError && <ErrorNotice error={mutationError} />}

                  <div className="space-y-2">
                    {items.map((it) => (
                      <Card key={it.id} className="p-4">
                        <div className="flex items-start gap-3">
                          <button
                            type="button"
                            className="mt-0.5"
                            aria-label={it.completed ? '标记为未完成' : '标记为已完成'}
                            onClick={() => setCompleted.mutate({ itemId: it.id, completed: !it.completed })}
                            disabled={Boolean(pendingItemIds[it.id])}
                          >
                            {it.completed ? (
                              <CheckCircle2 className="h-5 w-5 text-primary" />
                            ) : (
                              <Circle className="h-5 w-5 text-muted-foreground" />
                            )}
                          </button>
                          <div className="min-w-0 flex-1">
                            <div className={cn('font-medium', it.completed && 'line-through text-muted-foreground')}>
                              {it.title}
                            </div>
                            {it.description && <div className="text-sm text-muted-foreground mt-1">{it.description}</div>}
                            {it.due_at && (
                              <div className="text-xs text-muted-foreground mt-2">截止：{it.due_at}</div>
                            )}
                          </div>
                        </div>
                      </Card>
                    ))}
                  </div>
                </>
              )}
            </div>
          </ScrollArea>
        </main>
      </div>
    </div>
  )
}
