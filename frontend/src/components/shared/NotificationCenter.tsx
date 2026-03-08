import { useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Bell, CheckCircle2, XCircle } from 'lucide-react'
import { listTasks, type UnifiedTask } from '@/api/tasks'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useNotificationStore } from '@/stores/useNotificationStore'
import { useToastStore } from '@/stores/useToastStore'
import { useAuthStore } from '@/stores/useAuthStore'
import { cn } from '@/lib/utils'

const SEEN_STATUS_STORAGE_KEY = 'task.status_seen.v1'

function loadSeenStatuses(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(SEEN_STATUS_STORAGE_KEY)
    if (!raw) return {}
    const obj = JSON.parse(raw)
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) return obj as Record<string, string>
    return {}
  } catch {
    return {}
  }
}

function saveSeenStatuses(obj: Record<string, string>): void {
  try {
    window.localStorage.setItem(SEEN_STATUS_STORAGE_KEY, JSON.stringify(obj))
  } catch {
    // ignore
  }
}

export function NotificationCenter() {
  const navigate = useNavigate()
  const { notifications, push, markAllRead, remove, clear } = useNotificationStore()
  const { pushToast } = useToastStore()
  const { isAuthenticated, token } = useAuthStore()
  const unreadCount = useMemo(() => notifications.filter((n) => !n.read).length, [notifications])

  const seenRef = useRef<Record<string, string> | null>(null)
  if (seenRef.current == null && typeof window !== 'undefined') {
    seenRef.current = loadSeenStatuses()
  }

  const { data } = useQuery({
    queryKey: ['taskNotifications'],
    queryFn: () => listTasks({ limit: 200 }),
    refetchInterval: 5000,
    enabled: isAuthenticated && Boolean(token),
  })

  useEffect(() => {
    const tasks = (data?.tasks || []) as UnifiedTask[]
    if (!seenRef.current) return

    const seen = { ...seenRef.current }
    let changed = false

    for (const t of tasks) {
      const id = String((t as any).id || '')
      if (!id) continue
      const status = String((t as any).status || '')
      const prev = seen[id]
      if (prev !== status) {
        seen[id] = status
        changed = true

        const terminal = status === 'completed' || status === 'failed' || status === 'canceled' || status === 'cancelled'
        if (terminal) {
          push({
            id: `${id}-${status}-${String((t as any).updated_at || '')}`,
            taskId: id,
            title: String((t as any).title || id),
            status,
            createdAt: String((t as any).updated_at || new Date().toISOString()),
          })
          pushToast({
            id: `toast-${id}-${status}-${String((t as any).updated_at || '')}`,
            taskId: id,
            title: String((t as any).title || id),
            status,
          })
        }
      }
    }

    if (changed) {
      seenRef.current = seen
      saveSeenStatuses(seen)
    }
  }, [data, push, pushToast])

  const openTask = (taskId: string) => {
    navigate(`/tasks?id=${encodeURIComponent(taskId)}`)
  }

  return (
    <DropdownMenu
      onOpenChange={(open) => {
        if (open) markAllRead()
      }}
    >
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="icon" className="relative h-8 w-8" aria-label="通知">
          <Bell className="h-4 w-4" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 h-4 min-w-4 px-1 rounded-full bg-destructive text-destructive-foreground text-[10px] leading-4 text-center">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          <span>通知</span>
          {notifications.length > 0 && (
            <Button type="button" size="sm" variant="ghost" onClick={clear} className="h-7 px-2 text-xs">
              清空
            </Button>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />

        {notifications.length === 0 ? (
          <div className="px-3 py-6 text-sm text-muted-foreground text-center">暂无通知</div>
        ) : (
          notifications.slice(0, 20).map((n) => {
            const isFail = String(n.status) === 'failed'
            return (
              <DropdownMenuItem
                key={n.id}
                className={cn('flex items-start gap-2 py-2', !n.read && 'bg-accent/30')}
                onClick={() => openTask(n.taskId)}
              >
                {isFail ? <XCircle className="h-4 w-4 text-destructive mt-0.5" /> : <CheckCircle2 className="h-4 w-4 text-primary mt-0.5" />}
                <div className="min-w-0 flex-1">
                  <div className="text-sm truncate">{n.title}</div>
                  <div className="text-[11px] text-muted-foreground truncate">{n.taskId}</div>
                </div>
                <Badge variant={isFail ? 'destructive' : 'secondary'} className="ml-2">
                  {isFail ? '失败' : '完成'}
                </Badge>
                <button
                  type="button"
                  className="ml-1 text-muted-foreground hover:text-foreground"
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    remove(n.id)
                  }}
                  aria-label="移除通知"
                >
                  ×
                </button>
              </DropdownMenuItem>
            )
          })
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
