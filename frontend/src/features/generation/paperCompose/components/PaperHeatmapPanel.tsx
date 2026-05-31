import { useMemo, useState } from 'react'
import { BarChart3, ChevronDown, ChevronRight } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Question } from '@/types'

import {
  bucketDifficulty,
  buildHeatmap,
  DIFFICULTY_BUCKETS,
  DIFFICULTY_LABELS,
  type DifficultyBucket,
} from '../utils/heatmap'

interface PaperHeatmapPanelProps {
  questions: Question[]
}

const BUCKET_BG: Record<DifficultyBucket, string> = {
  easy: 'rgb(34, 197, 94)',     // green-500
  medium: 'rgb(234, 179, 8)',   // yellow-500
  hard: 'rgb(239, 68, 68)',     // red-500
  unknown: 'rgb(148, 163, 184)', // slate-400
}

function cellBackground(bucket: DifficultyBucket, count: number, maxCount: number): string {
  if (count === 0) return 'transparent'
  const intensity = maxCount > 0 ? 0.15 + (count / maxCount) * 0.75 : 0.4
  const base = BUCKET_BG[bucket]
  return base.replace('rgb(', 'rgba(').replace(')', `, ${intensity.toFixed(2)})`)
}

export function PaperHeatmapPanel({ questions }: PaperHeatmapPanelProps) {
  const [expanded, setExpanded] = useState(true)

  const heatmap = useMemo(() => buildHeatmap(questions), [questions])
  const bucketTotals = useMemo(() => {
    const totals: Record<DifficultyBucket, number> = { easy: 0, medium: 0, hard: 0, unknown: 0 }
    for (const q of questions) {
      const b = bucketDifficulty(q)
      totals[b] += 1
    }
    return totals
  }, [questions])

  if (heatmap.knowledgePoints.length === 0) {
    return null
  }

  const cellByKey = new Map(heatmap.cells.map((c) => [`${c.knowledgePoint} ${c.bucket}`, c]))

  return (
    <div className="mb-8 p-4 rounded-xl bg-muted/30 border border-border/50 print:hidden">
      <div className="flex items-center justify-between mb-3">
        <button
          type="button"
          className="flex items-center gap-2 font-semibold text-left"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <BarChart3 className="h-4 w-4 text-primary" />
          组卷诊断：考点 × 难度热力图
        </button>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {DIFFICULTY_BUCKETS.filter((b) => bucketTotals[b] > 0).map((b) => (
            <Badge
              key={b}
              variant="outline"
              className="bg-background"
              style={{ borderColor: BUCKET_BG[b], color: BUCKET_BG[b] }}
            >
              {DIFFICULTY_LABELS[b]} {bucketTotals[b]}
            </Badge>
          ))}
          {heatmap.uncategorizedCount > 0 && (
            <Badge variant="outline" className="bg-background">
              未标知识点 {heatmap.uncategorizedCount}
            </Badge>
          )}
        </div>
      </div>

      {expanded && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-separate border-spacing-1">
            <thead>
              <tr>
                <th className="text-left font-normal text-muted-foreground px-2 py-1">知识点 \ 难度</th>
                {DIFFICULTY_BUCKETS.map((b) => (
                  <th key={b} className="font-normal text-muted-foreground px-2 py-1 text-center">
                    {DIFFICULTY_LABELS[b]}
                  </th>
                ))}
                <th className="font-normal text-muted-foreground px-2 py-1 text-center">合计</th>
              </tr>
            </thead>
            <tbody>
              {heatmap.knowledgePoints.map((kp) => {
                const rowCells = DIFFICULTY_BUCKETS.map((b) => cellByKey.get(`${kp} ${b}`))
                const rowTotal = rowCells.reduce((sum, c) => sum + (c?.count ?? 0), 0)
                return (
                  <tr key={kp}>
                    <td className="px-2 py-1 text-foreground/80 max-w-[14rem] truncate" title={kp}>
                      {kp}
                    </td>
                    {DIFFICULTY_BUCKETS.map((b) => {
                      const cell = cellByKey.get(`${kp} ${b}`)
                      const count = cell?.count ?? 0
                      const bg = cellBackground(b, count, heatmap.maxCellCount)
                      return (
                        <td
                          key={b}
                          className="text-center px-2 py-1 rounded transition-colors"
                          style={{ backgroundColor: bg }}
                          title={
                            count > 0
                              ? `${kp} · ${DIFFICULTY_LABELS[b]}：${count} 道\n${(cell?.questionIds || []).join(', ')}`
                              : `${kp} · ${DIFFICULTY_LABELS[b]}：0 道`
                          }
                        >
                          <span className={count > 0 ? 'font-medium text-foreground' : 'text-muted-foreground/40'}>
                            {count > 0 ? count : '·'}
                          </span>
                        </td>
                      )
                    })}
                    <td className="text-center px-2 py-1 font-medium text-foreground/70">{rowTotal}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
            <span>共 {heatmap.totalQuestions} 道题，展示 Top {heatmap.knowledgePoints.length} 知识点</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => setExpanded(false)}
            >
              收起
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
