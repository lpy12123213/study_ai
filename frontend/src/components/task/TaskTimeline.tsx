import { motion, AnimatePresence } from 'framer-motion'
import { TaskStep as TaskStepComponent } from './TaskStep'
import type { TaskStep } from '@/types'

interface TaskTimelineProps {
  steps: TaskStep[]
}

export function TaskTimeline({ steps }: TaskTimelineProps) {
  return (
    <div className="relative">
      {/* Timeline line */}
      <div className="absolute left-3 top-0 bottom-0 w-px bg-border" />
      
      {/* Steps */}
      <AnimatePresence mode="popLayout">
        {steps.map((step, index) => (
          <motion.div
            key={step.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ delay: index * 0.05 }}
          >
            <TaskStepComponent
              step={step}
              isLast={index === steps.length - 1}
            />
          </motion.div>
        ))}
      </AnimatePresence>
      
      {steps.length === 0 && (
        <div className="text-center text-muted-foreground text-sm py-8">
          等待任务开始...
        </div>
      )}
    </div>
  )
}
