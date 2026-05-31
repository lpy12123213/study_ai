import { Layers } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

export interface OneClickPaperFormProps {
  paperName: string
  onPaperNameChange: (value: string) => void
  totalPoints: number
  onTotalPointsChange: (value: number) => void
  timeLimit: number
  onTimeLimitChange: (value: number) => void
  hardPct: number
  onHardPctChange: (value: number) => void
  useArchive: boolean
  onUseArchiveChange: (value: boolean) => void
  error: string
}

export function OneClickPaperForm({
  paperName,
  onPaperNameChange,
  totalPoints,
  onTotalPointsChange,
  timeLimit,
  onTimeLimitChange,
  hardPct,
  onHardPctChange,
  useArchive,
  onUseArchiveChange,
  error,
}: OneClickPaperFormProps) {
  return (
    <Card className="surface-raised">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Layers className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">一键组卷参数</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <label className="text-sm font-medium mb-1.5 block">试卷标题（可选）</label>
          <Input
            placeholder="留空将自动生成"
            value={paperName}
            onChange={(e) => onPaperNameChange(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium mb-1.5 block">总分</label>
            <Input
              type="number"
              min={30}
              max={300}
              value={totalPoints}
              onChange={(e) => onTotalPointsChange(parseInt(e.target.value) || 150)}
            />
          </div>
          <div>
            <label className="text-sm font-medium mb-1.5 block">考试时长（分钟）</label>
            <Input
              type="number"
              min={30}
              max={240}
              value={timeLimit}
              onChange={(e) => onTimeLimitChange(parseInt(e.target.value) || 120)}
            />
          </div>
        </div>

        <div>
          <label className="text-sm font-medium mb-1.5 block">难题占比（{hardPct}%）</label>
          <input
            type="range"
            min={0}
            max={60}
            value={hardPct}
            onChange={(e) => onHardPctChange(parseInt(e.target.value) || 0)}
            className="w-full accent-primary"
          />
          <div className="mt-1 text-xs text-muted-foreground">剩余比例会按“简单 40% / 中等 60%”自动分配。</div>
        </div>

        <div className="flex items-center gap-2">
          <input
            id="one-click-use-archive"
            type="checkbox"
            checked={useArchive}
            onChange={(e) => onUseArchiveChange(e.target.checked)}
            className="h-4 w-4"
          />
          <label htmlFor="one-click-use-archive" className="text-sm text-muted-foreground">
            使用最近一次自学资料作为素材（如果存在）
          </label>
        </div>

        {error ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
