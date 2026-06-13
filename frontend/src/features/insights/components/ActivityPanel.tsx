import { Flame, ListTodo } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import type { ActivityInsights } from '@/api/insights'
import { formatPercent } from '@/features/insights/components/format'

export function ActivityPanel({ data }: { data?: ActivityInsights }) {
  const plan = data?.plan_completion

  return (
    <Card className="aurora-insights-card overflow-hidden">
      <CardHeader className="border-b border-border pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">学习活跃度</div>
            <CardTitle className="mt-1 text-xl">计划与连续学习</CardTitle>
          </div>
          <Flame className="h-5 w-5 text-[var(--semantic-warning-base)]" />
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="aurora-insights-metric p-4">
            <div className="text-xs text-muted-foreground">活跃天数</div>
            <div className="mt-2 font-mono text-3xl">{data?.active_days ?? 0}</div>
          </div>
          <div className="aurora-insights-metric p-4">
            <div className="text-xs text-muted-foreground">连续天数</div>
            <div className="mt-2 font-mono text-3xl">{data?.current_streak ?? 0}</div>
          </div>
        </div>

        <div className="aurora-insights-metric p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <ListTodo className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">学习计划</span>
            </div>
            <span className="font-mono text-sm text-muted-foreground">{formatPercent(plan?.ratio)}</span>
          </div>
          <Progress value={Number(plan?.ratio || 0) * 100} className="mt-3 h-2" />
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>已完成 {plan?.completed ?? 0}/{plan?.total ?? 0}</span>
            <span>逾期 {plan?.overdue ?? 0}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
