import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { PenSquare } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { EssayInsights } from '@/api/insights'
import {
  chartPercent,
  formatPercent,
  insightAxisTick,
  insightTooltipContentStyle,
  insightTooltipLabelStyle,
} from '@/features/insights/components/format'
import { PanelEmpty } from '@/features/insights/components/PanelEmpty'

export function EssayPanel({ data }: { data?: EssayInsights }) {
  const trend = data?.trend ?? []
  const byType = data?.by_type ?? []

  return (
    <Card className="aurora-insights-card overflow-hidden">
      <CardHeader className="border-b border-border pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">作文表现</div>
            <CardTitle className="mt-1 text-xl">得分趋势</CardTitle>
          </div>
          <PenSquare className="h-5 w-5 text-[var(--semantic-warning-base)]" />
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-5">
        <div className="aurora-insights-metric p-3">
          <div className="text-xs text-muted-foreground">平均作文得分</div>
          <div className="mt-2 font-mono text-2xl">{formatPercent(data?.avg_score_ratio)}</div>
        </div>

        {trend.length === 0 ? (
          <PanelEmpty>暂无作文评分数据</PanelEmpty>
        ) : (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trend} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle-color)" />
                <XAxis dataKey="date" tickLine={false} axisLine={false} tick={insightAxisTick} />
                <YAxis tickFormatter={chartPercent} domain={[0, 1]} tickLine={false} axisLine={false} tick={insightAxisTick} />
                <Tooltip
                  contentStyle={insightTooltipContentStyle}
                  formatter={(value) => formatPercent(Number(value))}
                  labelStyle={insightTooltipLabelStyle}
                />
                <Line
                  type="monotone"
                  dataKey="score_ratio"
                  stroke="var(--semantic-warning-base)"
                  strokeWidth={3}
                  dot={{ r: 3, strokeWidth: 2, fill: 'var(--color-env-void)' }}
                  activeDot={{ r: 5, stroke: 'var(--semantic-warning-base)', strokeWidth: 2 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {byType.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {byType.map((row) => (
              <div key={row.essay_type} className="aurora-insights-metric p-3">
                <div className="truncate text-sm">{row.essay_type}</div>
                <div className="mt-2 font-mono text-lg">{formatPercent(row.score_ratio)}</div>
                <div className="mt-1 text-xs text-muted-foreground">{row.count} 篇</div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
