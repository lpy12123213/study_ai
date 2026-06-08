import { Link } from 'react-router-dom'
import { ArrowRight, BookX } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import type { WrongbookInsights } from '@/api/insights'
import { formatPercent } from '@/features/insights/components/format'
import { PanelEmpty } from '@/features/insights/components/PanelEmpty'

export function WrongbookMasteryPanel({ data }: { data?: WrongbookInsights }) {
  const distribution = data?.mastery_distribution ?? []
  const weakPoints = data?.weak_points ?? []
  const maxBucket = Math.max(1, ...distribution.map((row) => Number(row.count || 0)))

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b border-border pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="font-mono text-xs text-muted-foreground">错题掌握度</div>
            <CardTitle className="mt-1 text-xl">薄弱知识点</CardTitle>
          </div>
          <BookX className="h-5 w-5 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent className="space-y-5 p-5">
        {(data?.total ?? 0) === 0 ? (
          <PanelEmpty>暂无错题掌握度数据</PanelEmpty>
        ) : (
          <>
            <div className="space-y-3">
              {distribution.map((row) => (
                <div key={row.bucket} className="grid grid-cols-[56px_minmax(0,1fr)_42px] items-center gap-3 text-sm">
                  <span className="font-mono text-xs text-muted-foreground">{row.label}</span>
                  <Progress value={(Number(row.count || 0) / maxBucket) * 100} className="h-2" />
                  <span className="text-right font-mono text-xs text-muted-foreground">{row.count}</span>
                </div>
              ))}
            </div>

            <div className="space-y-2">
              {weakPoints.map((point) => (
                <Link
                  key={point.knowledge_point}
                  to={`/wrongbook?knowledge_point=${encodeURIComponent(point.knowledge_point)}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-border bg-background px-3 py-2 transition-colors hover:bg-accent"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{point.knowledge_point}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{point.count} 题</div>
                  </div>
                  <div className="flex items-center gap-2 font-mono text-sm text-muted-foreground">
                    <span>{formatPercent(point.avg_mastery)}</span>
                    <ArrowRight className="h-4 w-4" />
                  </div>
                </Link>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
