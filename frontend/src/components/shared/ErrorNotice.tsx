import { useMemo, useState } from 'react'
import { AlertTriangle, Copy, RotateCcw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { apiClient, isApiError, type ApiErrorAction } from '@/api/client'

function formatErrorMessage(error: unknown): { message: string; requestId?: string; detail?: unknown; retriable?: boolean; actions?: ApiErrorAction[] } {
  if (isApiError(error)) {
    const msg = error.message || '请求失败'
    const requestId = error.requestId || undefined
    const detail = error.detail
    const retriable = Boolean(error.retriable)
    const actions = error.actions
    return { message: msg, requestId, detail, retriable, actions }
  }
  if (error instanceof Error) {
    return { message: error.message || '请求失败' }
  }
  if (typeof error === 'string' && error.trim()) {
    return { message: error.trim() }
  }
  return { message: '请求失败' }
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export function ErrorNotice(props: {
  error: unknown
  title?: string
  className?: string
  onRetry?: () => void
  onClose?: () => void
}) {
  const { error, title, className, onRetry, onClose } = props
  const info = useMemo(() => formatErrorMessage(error), [error])
  const [copied, setCopied] = useState(false)
  const [runningActionId, setRunningActionId] = useState<string | null>(null)

  const canRetry = Boolean(onRetry) && (info.retriable ?? true)

  const copyPayload = async () => {
    const payload = isApiError(error)
      ? {
          code: error.code,
          status: error.status,
          message: error.message,
          requestId: error.requestId,
          detail: error.detail,
        }
      : { message: info.message, requestId: info.requestId, detail: info.detail }

    const ok = await copyToClipboard(JSON.stringify(payload, null, 2))
    setCopied(ok)
    if (ok) {
      window.setTimeout(() => setCopied(false), 1500)
    }
  }

  const runAction = async (action: ApiErrorAction) => {
    if (!action.request) return
    try {
      setRunningActionId(action.id)
      await apiClient.request({
        method: action.request.method,
        url: action.request.url,
        data: action.request.body,
      })
      onRetry?.()
    } finally {
      setRunningActionId(null)
    }
  }

  return (
    <div className={cn('rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive', className)}>
      <div className="flex items-start gap-3">
        <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="font-medium">{title || '出错了'}</div>
              <div className="mt-1 whitespace-pre-wrap break-words text-destructive/90">{info.message}</div>
              {info.requestId && (
                <div className="mt-1 text-xs text-destructive/80">
                  requestId: <span className="font-mono">{info.requestId}</span>
                </div>
              )}
            </div>
            {onClose && (
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} aria-label="Close">
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {canRetry && (
              <Button type="button" size="sm" variant="secondary" onClick={onRetry}>
                <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
                重试
              </Button>
            )}
            <Button type="button" size="sm" variant="outline" onClick={copyPayload}>
              <Copy className="h-3.5 w-3.5 mr-1.5" />
              {copied ? '已复制' : '复制错误'}
            </Button>
          </div>

          {Array.isArray(info.actions) && info.actions.length > 0 && (
            <div className="mt-3 space-y-2">
              <div className="text-xs text-destructive/80">建议操作</div>
              <div className="flex flex-wrap gap-2">
                {info.actions.map((a) => (
                  <Button
                    key={a.id}
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={!a.request || runningActionId === a.id}
                    onClick={() => runAction(a)}
                  >
                    {runningActionId === a.id ? '执行中…' : a.title}
                  </Button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
