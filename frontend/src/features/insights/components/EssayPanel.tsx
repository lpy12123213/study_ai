import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { PenSquare } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { EssayInsights } from '@/api/insights'
import { chartPercent, formatPercent } from '@/features/insights/components/format'
import { PanelEmpty } from '@/features/insights/components/PanelEmpty'

export function EssayPanel({ data }: { data?: EssayInsights }) {
  const trend = data?.trend ?? []
  const byType = data?.by_type ?? []

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b border-border pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="font-mono text-xs text-muted-foreground">作文表现</div>
            <CardTitle className="mt-1 text-xl">得分趋势</CardTitle>
          </div>
          <PenSquare className="h-5 w-5 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-5">
        <div className="rounded-md border border-border bg-background p-3">
          <div className="text-xs text-muted-foreground">平均作文得分</div>
          <div className="mt-2 font-mono text-2xl">{formatPercent(data?.avg_score_ratio)}</div>
        </div>

        {trend.length === 0 ? (
          <PanelEmpty>暂无作文评分数据</PanelEmpty>
        ) : (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trend} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={chartPercent} domain={[0, 1]} tickLine={false} axisLine={false} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value) => formatPercent(Number(value))} labelClassName="text-foreground" />
                <Line type="monotone" dataKey="score_ratio" stroke="var(--semantic-warning)" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {byType.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {byType.map((row) => (
              <div key={row.essay_type} className="rounded-md border border-border bg-background p-3">
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
