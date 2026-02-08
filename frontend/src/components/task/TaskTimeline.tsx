import { motion, AnimatePresence } from 'framer-motion'
import { TaskStep as TaskStepComponent } from './TaskStep'
import type { TaskStep } from '@/types'

/** Generic boilerplate step titles to hide */
const NOISE_PATTERNS = [
  '接收请求',
  '开始生成',
  '初始化上下文',
  '初始化',
  '计划：',
  '计划:',
]

function isNoiseStep(step: TaskStep): boolean {
  const t = (step.title || '').trim()
  // Match noise patterns
  if (NOISE_PATTERNS.some((p) => t.includes(p))) return true
  // Hide only extremely long non-tool steps (likely raw dumps).
  // For study-materials, we want to keep "thinking" steps visible.
  if (!step.toolName && t.length > 600) return true
  return false
}

interface TaskTimelineProps {
  steps: TaskStep[]
}

export function TaskTimeline({ steps }: TaskTimelineProps) {
  const filtered = steps.filter((s) => !isNoiseStep(s))

  return (
    <div className="relative">
      {/* Timeline line */}
      <div className="absolute left-3 top-0 bottom-0 w-px bg-border" />
      
      {/* Steps */}
      <AnimatePresence mode="popLayout">
        {filtered.map((step, index) => (
          <motion.div
            key={step.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ delay: index * 0.05 }}
          >
            <TaskStepComponent
              step={step}
              isLast={index === filtered.length - 1}
            />
          </motion.div>
        ))}
      </AnimatePresence>
      
      {filtered.length === 0 && (
        <div className="text-center text-muted-foreground text-sm py-8">
          等待任务开始...
        </div>
      )}
    </div>
  )
}
