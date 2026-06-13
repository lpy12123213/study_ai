import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { BarChart3 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ExamInsights } from '@/api/insights'
import {
  chartPercent,
  formatPercent,
  insightAxisTick,
  insightTooltipContentStyle,
  insightTooltipLabelStyle,
} from '@/features/insights/components/format'
import { PanelEmpty } from '@/features/insights/components/PanelEmpty'

export function AccuracyByTypePanel({ data }: { data?: ExamInsights['accuracy_by_type'] }) {
  const rows = data ?? []

  return (
    <Card className="aurora-insights-card overflow-hidden">
      <CardHeader className="border-b border-border pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">题型正确率</div>
            <CardTitle className="mt-1 text-xl">按题型拆解</CardTitle>
          </div>
          <BarChart3 className="h-5 w-5 text-[var(--semantic-success-base)]" />
        </div>
      </CardHeader>
      <CardContent className="p-5">
        {rows.length === 0 ? (
          <PanelEmpty>暂无题型正确率数据</PanelEmpty>
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="accuracyGradient" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="var(--semantic-success-base)" stopOpacity={0.95} />
                    <stop offset="100%" stopColor="var(--accent-brand-base)" stopOpacity={0.48} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle-color)" />
                <XAxis dataKey="question_type" tickLine={false} axisLine={false} tick={insightAxisTick} />
                <YAxis tickFormatter={chartPercent} domain={[0, 1]} tickLine={false} axisLine={false} tick={insightAxisTick} />
                <Tooltip
                  contentStyle={insightTooltipContentStyle}
                  formatter={(value) => formatPercent(Number(value))}
                  labelStyle={insightTooltipLabelStyle}
                />
                <Bar dataKey="ratio" fill="url(#accuracyGradient)" radius={[10, 10, 2, 2]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
