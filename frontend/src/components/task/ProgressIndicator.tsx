import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import type { StepStatus } from '@/types'

interface ProgressIndicatorProps {
  current: number
  total: number
  status: StepStatus
  className?: string
}

const statusColors: Record<StepStatus, string> = {
  pending: 'bg-muted-foreground/40',
  running: 'bg-foreground/80',
  completed: 'bg-foreground/70',
  failed: 'bg-destructive',
  paused: 'bg-muted-foreground/60',
}

export function ProgressIndicator({
  current,
  total,
  status,
  className,
}: ProgressIndicatorProps) {
  const percentage = total > 0 ? (current / total) * 100 : 0

  return (
    <div className={cn("w-full", className)}>
      <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
        <span>{current} / {total} 步骤</span>
        <span>{Math.round(percentage)}%</span>
      </div>
      <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
        <motion.div
          className={cn("h-full rounded-full", statusColors[status])}
          initial={{ width: 0 }}
          animate={{ width: `${percentage}%` }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
        />
      </div>
    </div>
  )
}
