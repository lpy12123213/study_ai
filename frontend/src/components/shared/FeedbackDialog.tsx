import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bug, Copy, ExternalLink, Loader2, Paperclip, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { RichTextarea } from '@/components/shared/RichTextarea'
import { useAuthStore } from '@/stores/useAuthStore'
import { useRequestLogStore } from '@/stores/useRequestLogStore'
import { useNotificationStore } from '@/stores/useNotificationStore'
import * as feedbackApi from '@/api/feedback'

type FeedbackSeed = {
  title?: string
  description?: string
  context?: Record<string, unknown>
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

async function fileToDataUrl(file: File): Promise<string> {
  return await new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('read_failed'))
    reader.onload = () => resolve(String(reader.result || ''))
    reader.readAsDataURL(file)
  })
}

export function FeedbackDialog(props: {
  open: boolean
  onOpenChange: (open: boolean) => void
  seed?: FeedbackSeed
}) {
  const { open, onOpenChange, seed } = props
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const user = useAuthStore((s) => s.user)
  const requestLogs = useRequestLogStore((s) => s.items)
  const addToast = useNotificationStore((s) => s.addToast)

  const [title, setTitle] = useState('反馈')
  const [description, setDescription] = useState('')
  const [screenshotName, setScreenshotName] = useState('')
  const [screenshotDataUrl, setScreenshotDataUrl] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open) return
    setTitle((seed?.title || '反馈').trim() || '反馈')
    setDescription(String(seed?.description || ''))
    setScreenshotName('')
    setScreenshotDataUrl('')
    setNotice(null)
    setCopied(false)
  }, [open, seed?.description, seed?.title])

  const autoContext = useMemo(() => {
    const lastRequests = requestLogs.slice(0, 12)
    const route = `${location.pathname || ''}${location.search || ''}${location.hash || ''}`
    const ctx: Record<string, unknown> = {
      time: new Date().toISOString(),
      route,
      user: user
        ? { id: user.id, username: user.username, role: user.role || 'user' }
        : null,
      online: typeof navigator !== 'undefined' ? navigator.onLine : undefined,
      userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
      request_id: lastRequests[0]?.requestId,
      recent_requests: lastRequests,
    }
    if (screenshotDataUrl) {
      ctx.screenshot = { name: screenshotName || 'screenshot', data_url: screenshotDataUrl }
    }
    if (seed?.context && typeof seed.context === 'object' && !Array.isArray(seed.context)) {
      ctx.seed = seed.context
    }
    return ctx
  }, [location.hash, location.pathname, location.search, requestLogs, screenshotDataUrl, screenshotName, seed?.context, user])

  const payloadPreview = useMemo(() => {
    return JSON.stringify(
      {
        title: title.trim() || '反馈',
        description: description.trim(),
        context: autoContext,
      },
      null,
      2,
    )
  }, [autoContext, description, title])

  const create = useMutation({
    mutationFn: () =>
      feedbackApi.createFeedback({
        title: title.trim() || '反馈',
        description: description.trim(),
        context: autoContext,
      }),
    onSuccess: (fb) => {
      queryClient.invalidateQueries({ queryKey: ['feedback'] })
      addToast({ id: `feedback-${fb.id}`, title: '反馈已提交', status: 'completed' })
      onOpenChange(false)
      navigate('/feedback')
    },
    onError: () => {
      addToast({ id: `feedback-failed-${Date.now()}`, title: '反馈提交失败', status: 'failed' })
    },
  })

  const handlePickScreenshot = async (file: File | null) => {
    setNotice(null)
    if (!file) {
      setScreenshotName('')
      setScreenshotDataUrl('')
      return
    }
    if (file.size > 1_000_000) {
      setNotice('截图太大（>1MB），请压缩或裁剪后再上传。')
      return
    }
    try {
      const url = await fileToDataUrl(file)
      setScreenshotName(file.name)
      setScreenshotDataUrl(url)
    } catch {
      setNotice('读取截图失败。')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bug className="h-4 w-4 text-primary" />
            一键反馈
          </DialogTitle>
          <DialogDescription>自动携带 request_id、路由与最近请求记录，方便定位问题。</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-2">
            <label className="text-sm font-medium">标题</label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：导出 PDF 失败" />
          </div>

          <div className="grid gap-2">
            <label className="text-sm font-medium">描述</label>
            <RichTextarea
              value={description}
              onChange={setDescription}
              placeholder="发生了什么？期望是什么？可以复现的步骤？"
              ariaLabel="描述"
              debounceMs={0}
              minHeight={120}
              maxHeight={300}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" asChild>
              <label className="cursor-pointer">
                <Paperclip className="h-4 w-4 mr-2" />
                附加截图（可选）
                <input
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    void handlePickScreenshot(e.target.files?.[0] ?? null)
                  }}
                />
              </label>
            </Button>
            {screenshotDataUrl && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => handlePickScreenshot(null)}
                aria-label="移除截图"
              >
                <X className="h-4 w-4 mr-2" />
                移除截图
              </Button>
            )}
            {notice && <div className="text-xs text-destructive">{notice}</div>}
          </div>

          {screenshotDataUrl && (
            <div className="rounded-md border p-2 bg-muted/10">
              <div className="text-xs text-muted-foreground mb-2">截图预览：{screenshotName}</div>
              <img src={screenshotDataUrl} alt={screenshotName} className="max-h-56 rounded-md border object-contain" />
            </div>
          )}

          <div className="rounded-md border bg-muted/10 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-medium">将提交的上下文</div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    const ok = await copyToClipboard(payloadPreview)
                    setCopied(ok)
                    if (ok) window.setTimeout(() => setCopied(false), 1200)
                  }}
                >
                  <Copy className="h-4 w-4 mr-2" />
                  {copied ? '已复制' : '复制'}
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => navigate('/feedback')}>
                  <ExternalLink className="h-4 w-4 mr-2" />
                  反馈列表
                </Button>
              </div>
            </div>
            <pre className="mt-2 max-h-48 overflow-auto rounded-md border bg-background/60 p-2 text-[11px] leading-5">
              {payloadPreview}
            </pre>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={create.isPending}>
            取消
          </Button>
          <Button type="button" onClick={() => create.mutate()} disabled={create.isPending}>
            {create.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
            提交反馈
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
