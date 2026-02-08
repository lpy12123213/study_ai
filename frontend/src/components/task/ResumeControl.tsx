import { useState } from 'react'
import { motion } from 'framer-motion'
import { Play, RotateCcw, Trash2, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTaskStore } from '@/stores/useTaskStore'
import type { ResumableTask } from '@/types'

interface ResumeControlProps {
  taskId: string
  checkpoint: ResumableTask
}

export function ResumeControl({ taskId, checkpoint }: ResumeControlProps) {
  const [isResuming, setIsResuming] = useState(false)
  const { resumeTask, removeCheckpoint } = useTaskStore()

  const handleResume = async () => {
    setIsResuming(true)
    try {
      // Resume the task from checkpoint
      const resumedTask = resumeTask(taskId)
      if (resumedTask) {
        // In a real app, this would call the API to resume the task
        console.log('Resuming task:', resumedTask)
      }
    } finally {
      setIsResuming(false)
    }
  }

  const handleDiscard = () => {
    removeCheckpoint(taskId)
  }

  const completedCount = checkpoint.checkpoint.completedSteps.length
  const totalCount = checkpoint.totalSteps

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-4 bg-muted/40 border-b border-border"
    >
      <div className="flex items-start gap-3">
        <div className="h-8 w-8 rounded-full bg-muted ring-1 ring-border/60 flex items-center justify-center shrink-0">
          <AlertCircle className="h-4 w-4 text-foreground" />
        </div>
        
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-medium">任务已暂停</h4>
          <p className="text-xs text-muted-foreground mt-0.5">
            已完成 {completedCount}/{totalCount} 个步骤，可从断点继续执行
          </p>
          
          {/* Progress bar */}
          <div className="mt-2 h-1.5 w-full bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-foreground/70"
              style={{ width: `${(completedCount / totalCount) * 100}%` }}
            />
          </div>
          
          {/* Actions */}
          <div className="flex items-center gap-2 mt-3">
            <Button
              size="sm"
              onClick={handleResume}
              disabled={isResuming}
              className="gap-1"
            >
              {isResuming ? (
                <RotateCcw className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3" />
              )}
              继续执行
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleDiscard}
              className="gap-1 text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="h-3 w-3" />
              放弃
            </Button>
          </div>
        </div>
      </div>
    </motion.div>
  )
}
