import { motion } from 'framer-motion'
import { Pause } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
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

  return (
    <div className="w-[360px] h-full flex flex-col glass">
      {/* Header */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold">任务执行</h3>
          <div className="flex items-center gap-1">
            {isResumable && !isPaused && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={handlePause}
              >
                <Pause className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
        
        {/* Progress indicator */}
        <div className="mt-2">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>
              {currentSteps.filter((s) => s.status === 'completed').length} / {currentSteps.length} 步骤
            </span>
            <span>
              {Math.round(
                (currentSteps.filter((s) => s.status === 'completed').length /
                  currentSteps.length) *
                  100
              )}%
            </span>
          </div>
          <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-foreground/80"
              initial={{ width: 0 }}
              animate={{
                width: `${
                  (currentSteps.filter((s) => s.status === 'completed').length /
                    currentSteps.length) *
                  100
                }%`,
              }}
              transition={{ duration: 0.3 }}
            />
          </div>
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
