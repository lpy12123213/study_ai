import { ListChecks } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { UnifiedTask } from '@/api/tasks'
import { useI18n } from '@/i18n'

type TaskRailProps = {
  isAuthenticated: boolean
  isCollapsed: boolean
  runningTasks: UnifiedTask[]
  onOpenTaskCenter: () => void
  onOpenTask: (taskId: string) => void
}

export function TaskRail({
  isAuthenticated,
  isCollapsed,
  runningTasks,
  onOpenTask,
  onOpenTaskCenter,
}: TaskRailProps) {
  const { t } = useI18n()

  if (!isAuthenticated) return null

  return (
    <div className="mb-4">
      {!isCollapsed && (
        <Button type="button" variant="ghost" size="sm" className="w-full justify-start gap-2" onClick={onOpenTaskCenter}>
          <ListChecks className="h-4 w-4" />
          {t('history.taskCenter')}
          {runningTasks.length > 0 && (
            <Badge variant="secondary" className="ml-auto">
              {runningTasks.length}
            </Badge>
          )}
        </Button>
      )}

      {isCollapsed && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="mx-auto h-8 w-8 relative"
          onClick={onOpenTaskCenter}
          aria-label={t('history.taskCenter')}
          title={t('history.taskCenter')}
        >
          <ListChecks className="h-4 w-4" />
          {runningTasks.length > 0 && <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-primary" />}
        </Button>
      )}

      {!isCollapsed && runningTasks.length > 0 && (
        <div className="mt-2 space-y-1">
          <div className="px-2 text-xs font-medium text-muted-foreground/70">{t('history.running')}</div>
          {runningTasks.map((task) => (
            <button
              key={task.id}
              type="button"
              onClick={() => onOpenTask(task.id)}
              className="w-full flex items-center justify-between gap-2 px-2 py-1 rounded-md text-xs text-muted-foreground hover:bg-accent/50 hover:text-foreground transition-colors"
              title={task.title}
              aria-label={t('history.openTask', { title: task.title })}
            >
              <span className="truncate">{task.title}</span>
              <span className="shrink-0 font-mono">{Math.round(Number(task.progress || 0))}%</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
