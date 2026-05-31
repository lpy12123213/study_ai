import { BarChart3, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { PaperAnalysis } from '@/types'

export interface PaperAnalysisPanelProps {
  analysis: PaperAnalysis | undefined
  paperId: string | undefined
  isLoadingAnalysis: boolean
  analysisError: unknown
  onLoadAnalysis: () => void
}

export function PaperAnalysisPanel({
  analysis,
  paperId,
  isLoadingAnalysis,
  analysisError,
  onLoadAnalysis,
}: PaperAnalysisPanelProps) {
  if (analysis) {
    return (
      <div className="mb-8 p-4 rounded-xl bg-muted/30 border border-border/50 print:hidden">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 font-semibold">
            <BarChart3 className="h-4 w-4 text-primary" />
            AI 智能分析
          </div>
          <Badge variant="outline" className="bg-background">
            难度系数 {Number.isFinite(analysis.difficultyScore) ? analysis.difficultyScore.toFixed(2) : '--'}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground leading-6">
          {analysis.aiComment || '暂无详细评语'}
        </p>
      </div>
    )
  }

  return (
    <div className="mb-8 p-4 rounded-xl bg-muted/30 border border-border/50 print:hidden">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-semibold">
            <BarChart3 className="h-4 w-4 text-primary" />
            AI 智能分析
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            默认不请求外部分析服务。需要时再手动加载，并复用缓存结果。
          </p>
          {!!analysisError && (
            <p className="mt-2 text-sm text-destructive">
              加载失败，请稍后重试。
            </p>
          )}
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onLoadAnalysis}
          disabled={!paperId || isLoadingAnalysis}
        >
          {isLoadingAnalysis ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <BarChart3 className="h-4 w-4 mr-2" />
          )}
          加载分析
        </Button>
      </div>
    </div>
  )
}
