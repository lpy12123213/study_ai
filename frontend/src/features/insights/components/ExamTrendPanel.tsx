import { Link } from 'react-router-dom'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ArrowRight, ClipboardCheck } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ExamInsights } from '@/api/insights'
import { chartPercent, formatPercent, formatScore } from '@/features/insights/components/format'
import { PanelEmpty } from '@/features/insights/components/PanelEmpty'

export function ExamTrendPanel({ data }: { data?: ExamInsights }) {
  const trend = data?.trend ?? []
  const recent = data?.recent ?? []

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b border-border pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="font-mono text-xs text-muted-foreground">考试表现</div>
            <CardTitle className="mt-1 text-xl">成绩趋势</CardTitle>
          </div>
          <ClipboardCheck className="h-5 w-5 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-md border border-border bg-background p-3">
            <div className="text-xs text-muted-foreground">平均得分</div>
            <div className="mt-2 font-mono text-2xl">{formatPercent(data?.avg_score_ratio)}</div>
          </div>
          <div className="rounded-md border border-border bg-background p-3">
            <div className="text-xs text-muted-foreground">客观题</div>
            <div className="mt-2 font-mono text-2xl">{formatPercent(data?.objective?.ratio)}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {data?.objective?.correct ?? 0}/{data?.objective?.total ?? 0}
            </div>
          </div>
          <div className="rounded-md border border-border bg-background p-3">
            <div className="text-xs text-muted-foreground">主观题</div>
            <div className="mt-2 font-mono text-2xl">{formatPercent(data?.subjective?.ratio)}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {formatScore(data?.subjective?.score)}/{formatScore(data?.subjective?.max_score)}
            </div>
          </div>
        </div>

        {trend.length === 0 ? (
          <PanelEmpty>暂无考试成绩数据</PanelEmpty>
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trend} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fontSize: 12 }} />
                <YAxis tickFormatter={chartPercent} domain={[0, 1]} tickLine={false} axisLine={false} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value) => formatPercent(Number(value))} labelClassName="text-foreground" />
                <Line type="monotone" dataKey="score_ratio" stroke="var(--semantic-info)" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        <div className="space-y-2">
          {recent.length === 0 && <div className="text-sm text-muted-foreground">暂无最近交卷记录</div>}
          {recent.map((item) => (
            <Link
              key={item.session_id}
              to={`/exam/${encodeURIComponent(item.session_id)}/result`}
              className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm transition-colors hover:bg-accent"
            >
              <span className="truncate">{item.paper_name || '未命名试卷'}</span>
              <span className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
                {formatPercent(item.score_ratio)}
                <ArrowRight className="h-4 w-4" />
              </span>
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
