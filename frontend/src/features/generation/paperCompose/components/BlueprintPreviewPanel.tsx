import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight, CheckCircle2, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { TaskProgressHeader } from '@/components/task/TaskProgressHeader'
import { cn } from '@/lib/utils'
import type { Paper, TaskStep } from '@/types'
import type { SlotShortfall } from '@/features/generation/paperCompose/utils/slotShortfalls'
import type { OneClickPaperState } from '@/features/generation/paperCompose/hooks/useOneClickPaper'
import type { BlueprintMode } from '@/features/generation/paperCompose/hooks/useBlueprintDraft'

export interface BlueprintPreviewPanelProps {
  mode: BlueprintMode
  isComposing: boolean
  taskId: string | undefined
  progressPct: number
  result: Paper | null
  taskSteps: TaskStep[]
  slotShortfalls: SlotShortfall[]
  onFillShortfalls: () => void
  oneClick: Pick<OneClickPaperState, 'isGenerating' | 'progress' | 'steps' | 'result'>
}

export function BlueprintPreviewPanel({
  mode,
  isComposing,
  taskId,
  progressPct,
  result,
  taskSteps,
  slotShortfalls,
  onFillShortfalls,
  oneClick,
}: BlueprintPreviewPanelProps) {
  const spinning = (mode === 'blueprint' && isComposing) || (mode === 'one_click' && oneClick.isGenerating)

  return (
    <div className="col-span-5 h-full bg-sidebar-background border-l border-border flex flex-col overflow-hidden">
      <div className="p-6 border-b border-border">
        <h3 className="font-semibold mb-4 flex items-center gap-2">
          <Loader2 className={cn('h-4 w-4', spinning && 'animate-spin')} />
          任务执行
        </h3>

        {mode === 'blueprint' ? (
          taskId ? (
            <TaskProgressHeader taskId={taskId} compact />
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>进度</span>
                <span>{Math.round(progressPct)}%</span>
              </div>
              <Progress value={progressPct} className="h-2" />
            </div>
          )
        ) : (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>进度</span>
              <span>{Math.round(oneClick.progress)}%</span>
            </div>
            <Progress value={oneClick.progress} className="h-2" />
          </div>
        )}
      </div>

      <ScrollArea className="flex-1">
        <div className="p-6">
          {mode === 'blueprint' && result ? (
            <div className="text-center py-10">
              <div className="h-16 w-16 bg-green-100 dark:bg-green-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
                <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
              </div>
              <h3 className="text-lg font-medium mb-2">组卷完成</h3>
              <p className="text-muted-foreground mb-6">已生成试卷，包含 {result.questions.length} 道题目</p>

              {slotShortfalls.length > 0 && (
                <div className="mx-auto max-w-md mb-6 rounded-xl border border-amber-200/60 bg-amber-50/60 dark:border-amber-900/40 dark:bg-amber-900/10 p-4 text-left">
                  <div className="flex items-center gap-2 font-medium text-amber-900 dark:text-amber-200 mb-2">
                    <AlertTriangle className="h-4 w-4" />
                    槽位缺题提示
                  </div>
                  <div className="text-xs text-amber-900/80 dark:text-amber-200/80 space-y-1">
                    {slotShortfalls.slice(0, 6).map((s) => (
                      <div key={s.slotIndex}>
                        槽位 #{s.slotIndex + 1}：{s.questionType || '题型'} × {s.difficulty || '难度'}，缺{' '}
                        {s.requested - s.selected} 题
                      </div>
                    ))}
                    {slotShortfalls.length > 6 && <div>… 共 {slotShortfalls.length} 个槽位缺题</div>}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="bg-background"
                      onClick={onFillShortfalls}
                      disabled={isComposing}
                    >
                      一键重试补齐
                    </Button>
                  </div>
                </div>
              )}
              <Button asChild className="gap-2">
                <Link to={`/papers/${result.id}`}>
                  查看试卷 <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </div>
          ) : mode === 'one_click' && oneClick.result ? (
            <div className="text-center py-10">
              <div className="h-16 w-16 bg-green-100 dark:bg-green-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
                <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
              </div>
              <h3 className="text-lg font-medium mb-2">一键组卷完成</h3>
              <p className="text-muted-foreground mb-6">已生成试卷，包含 {oneClick.result.questionCount} 道题目</p>
              <Button asChild className="gap-2">
                <Link to={`/papers/${oneClick.result.paperId}`}>
                  查看试卷 <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
            </div>
          ) : (
            <TaskTimeline steps={mode === 'blueprint' ? taskSteps : oneClick.steps} />
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
