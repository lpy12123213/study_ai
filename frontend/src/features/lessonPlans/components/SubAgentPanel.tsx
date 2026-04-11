import { useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { CheckCircle2, Circle, Layers, Loader2, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SubAgentActivity } from '@/features/lessonPlans/types'

export function SubAgentPanel({ activities }: { activities: SubAgentActivity[] }) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!scrollRef.current) return
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [activities])

  if (activities.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-muted-foreground text-sm p-6">
        <Layers className="h-10 w-10 mb-3 opacity-30" />
        <p>等待知识点拆分…</p>
        <p className="text-xs mt-1 opacity-60">SubAgent 将逐个研究每个知识点</p>
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="h-full overflow-auto p-4 space-y-3">
      <div className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-2">
        <Layers className="h-3.5 w-3.5" />
        知识点研究进度（{activities.filter((a) => a.status === 'completed').length}/{activities.length}）
      </div>

      {activities.map((activity, i) => (
        <motion.div
          key={activity.knowledgePoint}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.05 }}
          className={cn(
            'rounded-lg border p-3 transition-all',
            activity.status === 'running' && 'border-primary/50 bg-primary/5 shadow-sm',
            activity.status === 'completed' && 'border-border bg-card',
            activity.status === 'pending' && 'border-border/50 bg-muted/30 opacity-60',
            activity.status === 'failed' && 'border-destructive/40 bg-destructive/5'
          )}
        >
          <div className="flex items-center gap-2 mb-2">
            {activity.status === 'completed' && <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />}
            {activity.status === 'running' && <Loader2 className="h-4 w-4 text-primary animate-spin shrink-0" />}
            {activity.status === 'pending' && <Circle className="h-4 w-4 text-muted-foreground/40 shrink-0" />}
            {activity.status === 'failed' && <XCircle className="h-4 w-4 text-destructive shrink-0" />}
            <span className="text-sm font-medium truncate">{activity.knowledgePoint}</span>
          </div>

          {activity.steps.length > 0 && activity.status !== 'pending' && (
            <div className="ml-6 space-y-1">
              {activity.steps.map((step) => (
                <div key={step.id} className="flex items-center gap-2 text-xs text-muted-foreground">
                  {step.status === 'completed' && <CheckCircle2 className="h-3 w-3 text-green-500/70 shrink-0" />}
                  {step.status === 'running' && <Loader2 className="h-3 w-3 text-primary animate-spin shrink-0" />}
                  {step.status === 'pending' && <Circle className="h-3 w-3 opacity-40 shrink-0" />}
                  {step.status === 'failed' && <XCircle className="h-3 w-3 text-destructive/80 shrink-0" />}
                  <span className="truncate">{step.title}</span>
                </div>
              ))}
            </div>
          )}
        </motion.div>
      ))}
    </div>
  )
}

