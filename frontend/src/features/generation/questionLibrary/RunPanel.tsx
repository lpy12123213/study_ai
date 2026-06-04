import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Loader2, XCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { TaskProgressHeader } from '@/components/task/TaskProgressHeader'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { cn } from '@/lib/utils'
import { useTaskStore } from '@/stores/useTaskStore'
import type { TaskStep } from '@/types'
import type { QuestionLibraryTaskMeta } from '@/features/generation/questionLibrary/hooks/useQuestionLibraryTasks'

// Avoid returning a new array literal from Zustand selectors. React 19 will treat that
// as an unstable snapshot and can get stuck in an update loop.
const EMPTY_STEPS: TaskStep[] = []

function kindLabel(kind: string): string {
  if (kind === 'crawl') return '爬取入库'
  if (kind === 'generate') return 'AI 出题'
  if (kind === 'media_import') return '图片/PDF 录入'
  if (kind === 'score') return '思维评分'
  return '任务'
}

interface Props {
  task: QuestionLibraryTaskMeta | null
}

export function RunPanel(props: Props) {
  const { task } = props
  const [expanded, setExpanded] = useState(false)

  const taskId = String(task?.taskId || '').trim()
  const showUnifiedHeader = Boolean(taskId && task?.kind === 'generate')
  const steps = useTaskStore((s) => (taskId ? s.getTaskSteps(taskId) : EMPTY_STEPS))

  useEffect(() => {
    if (!task) return
    if (task.status === 'running') setExpanded(true)
  }, [task])

  const progress = Math.max(0, Math.min(100, Math.round(task?.progress || 0)))

  const headerText = useMemo(() => {
    if (!task) return ''
    const parts: string[] = [kindLabel(task.kind)]
    if (task.stage) parts.push(task.stage)
    return parts.filter(Boolean).join(' / ')
  }, [task])

  if (!task) return null

  return (
    <div className={cn('border-t bg-background', expanded ? 'h-[260px]' : 'h-[54px]')}>
      <div className="h-[54px] px-4 flex items-center justify-between gap-3">
        <button
          type="button"
          className="flex-1 min-w-0 text-left"
          onClick={() => setExpanded((v) => !v)}
        >
          <div className="flex items-center gap-2 min-w-0">
            {task.status === 'running' ? (
              <Loader2 className="h-4 w-4 animate-spin text-primary shrink-0" />
            ) : task.status === 'failed' ? (
              <XCircle className="h-4 w-4 text-destructive shrink-0" />
            ) : (
              <div className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
            )}
            <div className="text-sm font-medium truncate">{headerText}</div>
            <div className="text-xs text-muted-foreground shrink-0">{progress}%</div>
          </div>
          <div className="mt-2">
            <Progress value={progress} className="h-1.5" />
          </div>
        </button>

        {taskId && (
          <Button type="button" variant="outline" size="sm" className="h-9" asChild>
            <Link to={`/tasks?id=${encodeURIComponent(taskId)}`}>
              任务中心
            </Link>
          </Button>
        )}

        <Button type="button" variant="ghost" size="icon" className="h-9 w-9" onClick={() => setExpanded((v) => !v)}>
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
        </Button>
      </div>

      {expanded && (
        <div className="h-[calc(260px-54px)] border-t">
          <ScrollArea className="h-full">
            <div className="p-4">
              {task.error && <div className="text-sm text-destructive mb-3">{task.error}</div>}
              {showUnifiedHeader && <TaskProgressHeader taskId={taskId} compact className="mb-3" />}
              <TaskTimeline steps={steps} />
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  )
}

