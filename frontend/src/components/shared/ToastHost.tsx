import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, XCircle, X } from 'lucide-react'
import { useToastStore } from '@/stores/useToastStore'
import { cn } from '@/lib/utils'

const AUTO_DISMISS_MS = 6000

export function ToastHost() {
  const navigate = useNavigate()
  const { toasts, removeToast } = useToastStore()

  useEffect(() => {
    if (toasts.length === 0) return
    const timers = toasts.map((t) =>
      window.setTimeout(() => removeToast(t.id), AUTO_DISMISS_MS)
    )
    return () => {
      timers.forEach((id) => window.clearTimeout(id))
    }
  }, [toasts, removeToast])

  if (toasts.length === 0) return null

  return (
    <div className="fixed top-14 right-4 z-[60] flex flex-col gap-2 w-[340px] max-w-[calc(100vw-2rem)]">
      {toasts.map((t) => {
        const s = String(t.status)
        const isFail = s === 'failed' || s === 'canceled' || s === 'cancelled'
        const Icon = isFail ? XCircle : CheckCircle2
        return (
          <div
            key={t.id}
            className={cn(
              'rounded-lg border bg-background/95 backdrop-blur-sm shadow-lg p-3',
              isFail ? 'border-destructive/30' : 'border-border/60'
            )}
          >
            <div className="flex items-start gap-2">
              <Icon className={cn('h-4 w-4 mt-0.5 shrink-0', isFail ? 'text-destructive' : 'text-primary')} />
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                onClick={() => {
                  if (t.taskId) navigate(`/tasks?id=${encodeURIComponent(t.taskId)}`)
                  removeToast(t.id)
                }}
              >
                <div className="text-sm font-medium truncate">{t.title}</div>
                {t.taskId && <div className="text-[11px] text-muted-foreground truncate">{t.taskId}</div>}
              </button>
              <button
                type="button"
                className="text-muted-foreground hover:text-foreground"
                onClick={() => removeToast(t.id)}
                aria-label="关闭通知"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
