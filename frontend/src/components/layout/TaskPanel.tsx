import { Pause, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Progress } from '@/components/ui/progress'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { ResumeControl } from '@/components/task/ResumeControl'
import { useTaskStore } from '@/stores/useTaskStore'

export function TaskPanel() {
  const { activeTasks, checkpoints, pauseTask } = useTaskStore()
  
  const activeTaskEntries = Array.from(activeTasks.entries())

  // Prefer showing the most recent RUNNING task (Manus-style)
  const runningEntries = activeTaskEntries.filter(([, steps]) =>
    steps.some((s) => s.status === 'running')
  )

  const getLastStepTime = (steps: typeof runningEntries[number][1]) => {
    const last = steps[steps.length - 1]
    const t = last?.startTime || last?.endTime
    if (!t) return 0
    const ms = new Date(t).getTime()
    return Number.isFinite(ms) ? ms : 0
  }

  const preferredEntries = (runningEntries.length > 0 ? runningEntries : activeTaskEntries).sort(
    (a, b) => getLastStepTime(b[1]) - getLastStepTime(a[1])
  )

  const [currentTaskId, currentSteps] = preferredEntries[0] || [null, []]
  
  // Check if task is resumable (has checkpoint)
  const checkpoint = currentTaskId ? checkpoints.get(currentTaskId) : undefined
  const isResumable = checkpoint?.canResume ?? false
  const isPaused = checkpoint?.status === 'paused'

  const handlePause = () => {
    if (currentTaskId) {
      pauseTask(currentTaskId)
    }
  }

  if (!currentTaskId) {
    return null
  }

  const completedCount = currentSteps.filter((s) => s.status === 'completed').length
  const totalCount = currentSteps.length || 1
  const progressPercent = Math.round((completedCount / totalCount) * 100)

  return (
    <div className="w-full h-full flex flex-col bg-sidebar-background">
      {/* Header */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold flex items-center gap-2">
            {!isPaused && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
            任务执行
          </h3>
          <div className="flex items-center gap-1">
            {isResumable && !isPaused && (
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={handlePause}
              >
                <Pause className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
        
        {/* Progress indicator */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {completedCount} / {totalCount} 步骤
            </span>
            <span>{progressPercent}%</span>
          </div>
          <Progress value={progressPercent} className="h-1.5" />
        </div>
      </div>

      {/* Resume control (if paused) */}
      {isPaused && checkpoint && (
        <>
          <ResumeControl taskId={currentTaskId} checkpoint={checkpoint} />
          <Separator />
        </>
      )}

      {/* Task timeline */}
      <ScrollArea className="flex-1">
        <div className="p-4">
          <TaskTimeline steps={currentSteps} />
        </div>
      </ScrollArea>
    </div>
  )
}
