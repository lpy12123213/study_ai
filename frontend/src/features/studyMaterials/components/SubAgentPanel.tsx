import { useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { cn } from '@/lib/utils'
import type { SubAgentActivity } from '@/features/studyMaterials/types'

export function SubAgentPanel({
  activities,
  activeTab,
  onTabChange,
}: {
  activities: SubAgentActivity[]
  activeTab: string | null
  onTabChange: (kp: string) => void
}) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const scrollPositionsRef = useRef<Record<string, number>>({})

  const selectedKP = activeTab || activities[0]?.knowledgePoint || null
  const selectedActivity = activities.find((a) => a.knowledgePoint === selectedKP)

  useEffect(() => {
    if (!selectedKP) return
    requestAnimationFrame(() => {
      const el = scrollContainerRef.current
      if (!el) return
      el.scrollTop = scrollPositionsRef.current[selectedKP] ?? 0
    })
  }, [selectedKP])

  if (!activities.length) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-muted-foreground text-sm">
        等待知识点拆分...
      </div>
    )
  }

  const statusIcon = (status: SubAgentActivity['status']) => {
    if (status === 'pending') return <div className="h-2 w-2 rounded-full bg-muted-foreground/30" />
    if (status === 'running') return <Loader2 className="h-3 w-3 animate-spin text-primary" />
    if (status === 'failed') return <div className="h-2 w-2 rounded-full bg-destructive" />
    return <div className="h-2 w-2 rounded-full bg-green-500" />
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 p-2 border-b border-border bg-muted/30 shrink-0">
        {activities.map((activity) => {
          const isActive = activity.knowledgePoint === selectedKP
          return (
            <motion.button
              key={activity.knowledgePoint}
              onClick={() => {
                const el = scrollContainerRef.current
                if (el && selectedKP) {
                  scrollPositionsRef.current[selectedKP] = el.scrollTop
                }
                onTabChange(activity.knowledgePoint)
              }}
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18 }}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors',
                isActive
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
              )}
            >
              {statusIcon(activity.status)}
              <span>{activity.knowledgePoint}</span>
            </motion.button>
          )
        })}
      </div>

      {/* Content area */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-auto p-4 min-h-0 overscroll-contain"
      >
        <AnimatePresence mode="popLayout">
          {selectedActivity ? (
            <motion.div
              key={selectedKP}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.18 }}
            >
              <div className="flex items-center gap-2 mb-4">
                {statusIcon(selectedActivity.status)}
                <span className="text-sm font-medium">{selectedActivity.knowledgePoint}</span>
                <Badge
                  variant={
                    selectedActivity.status === 'running'
                      ? 'default'
                      : selectedActivity.status === 'completed'
                        ? 'secondary'
                        : selectedActivity.status === 'failed'
                          ? 'destructive'
                          : 'outline'
                  }
                  className="text-xs"
                >
                  {selectedActivity.status === 'pending'
                    ? '待处理'
                    : selectedActivity.status === 'running'
                      ? '进行中'
                      : selectedActivity.status === 'failed'
                        ? '失败'
                        : '已完成'}
                </Badge>
              </div>

              {selectedActivity.steps.length > 0 ? (
                <TaskTimeline steps={selectedActivity.steps} />
              ) : (
                <div className="text-sm text-muted-foreground">
                  {selectedActivity.status === 'pending' ? '等待开始...' : '暂无步骤记录'}
                </div>
              )}
            </motion.div>
          ) : (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="text-sm text-muted-foreground"
            >
              选择一个知识点查看详情
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

