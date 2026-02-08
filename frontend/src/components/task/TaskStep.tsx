import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Check,
  X,
  Loader2,
  Clock,
  Pause,
  ChevronRight,
  Wrench,
} from 'lucide-react'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { StepDetail } from './StepDetail'
import { cn, formatDuration, formatTime } from '@/lib/utils'
import type { TaskStep as TaskStepType, StepStatus } from '@/types'

interface TaskStepProps {
  step: TaskStepType
  isLast: boolean
}

const statusConfig: Record<
  StepStatus,
  { icon: typeof Check; color: string; bgColor: string }
> = {
  pending: {
    icon: Clock,
    color: 'text-muted-foreground',
    bgColor: 'bg-muted',
  },
  running: {
    icon: Loader2,
    color: 'text-foreground',
    bgColor: 'bg-foreground/10',
  },
  completed: {
    icon: Check,
    color: 'text-foreground',
    bgColor: 'bg-foreground/5',
  },
  failed: {
    icon: X,
    color: 'text-destructive',
    bgColor: 'bg-destructive/10',
  },
  paused: {
    icon: Pause,
    color: 'text-muted-foreground',
    bgColor: 'bg-muted',
  },
}

export function TaskStep({ step, isLast }: TaskStepProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const config = statusConfig[step.status]
  const Icon = config.icon

  // Calculate duration
  const duration =
    step.startTime && step.endTime
      ? new Date(step.endTime).getTime() - new Date(step.startTime).getTime()
      : null

  const hasDetails = step.input || step.output || step.error || step.toolName

  return (
    <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
      <div className={cn("relative pl-8", isLast ? "pb-0" : "pb-4")}>
        {/* Status indicator */}
        <div
          className={cn(
            "absolute left-0 top-0 h-6 w-6 rounded-full flex items-center justify-center",
            config.bgColor
          )}
        >
          <Icon
            className={cn(
              "h-3.5 w-3.5",
              config.color,
              step.status === 'running' && "animate-spin"
            )}
          />
        </div>

        {/* Content */}
        <div
          className={cn(
            "rounded-lg border p-3 transition-colors",
            step.status === 'running' && "border-foreground/30 bg-foreground/5",
            step.status === 'failed' && "border-destructive/40 bg-destructive/10",
            step.status === 'completed' && "border-border bg-card",
            (step.status === 'pending' || step.status === 'paused') &&
              "border-border bg-muted/50"
          )}
        >
          <CollapsibleTrigger asChild>
            <div
              className={cn(
                "flex items-start gap-2 cursor-pointer",
                hasDetails && "hover:opacity-80"
              )}
            >
              {/* Expand icon */}
              {hasDetails && (
                <motion.div
                  animate={{ rotate: isExpanded ? 90 : 0 }}
                  transition={{ duration: 0.2 }}
                  className="mt-0.5"
                >
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                </motion.div>
              )}

              <div className="flex-1 min-w-0">
                {/* Title */}
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{step.title}</span>
                  {step.toolName && (
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                      <Wrench className="h-3 w-3" />
                      {step.toolName}
                    </span>
                  )}
                </div>

                {/* Meta info */}
                <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                  {step.startTime && (
                    <span>{formatTime(step.startTime)}</span>
                  )}
                  {duration && (
                    <span className="text-muted-foreground/70">
                      {formatDuration(duration)}
                    </span>
                  )}
                </div>

                {/* Error preview */}
                {step.error && !isExpanded && (
                  <div className="mt-1 text-xs text-destructive truncate">
                    {step.error}
                  </div>
                )}
              </div>
            </div>
          </CollapsibleTrigger>

          {/* Expanded details */}
          <CollapsibleContent>
            <AnimatePresence>
              {isExpanded && hasDetails && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <StepDetail step={step} />
                </motion.div>
              )}
            </AnimatePresence>
          </CollapsibleContent>
        </div>

        {/* Children steps */}
        {step.children && step.children.length > 0 && (
          <div className="mt-2 ml-4 border-l border-dashed border-border pl-4">
            {step.children.map((child, idx) => (
              <TaskStep
                key={child.id}
                step={child}
                isLast={idx === step.children!.length - 1}
              />
            ))}
          </div>
        )}
      </div>
    </Collapsible>
  )
}
