import { useEffect, useMemo, useState } from 'react'
import { Copy, Loader2, QrCode as QrIcon, Link as LinkIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { QrCode } from '@/components/shared/QrCode'
import * as shareApi from '@/api/shareLinks'

export function secondsForPreset(preset: string): number | undefined {
  if (preset === '1h') return 3600
  if (preset === '1d') return 24 * 3600
  if (preset === '7d') return 7 * 24 * 3600
  if (preset === '30d') return 30 * 24 * 3600
  if (preset === 'never') return 0
  return undefined
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export function ShareLinkDialog(props: {
  open: boolean
  onOpenChange: (open: boolean) => void
  itemType: string
  itemId: string | number
  title?: string
}) {
  const { open, onOpenChange, itemType, itemId, title } = props
  const [preset, setPreset] = useState('7d')
  const [password, setPassword] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [meta, setMeta] = useState<any>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open) return
    setPreset('7d')
    setPassword('')
    setError(null)
    setMeta(null)
    setCopied(false)
  }, [open, itemId, itemType])

  const shareUrl = useMemo(() => {
    const tok = String(meta?.token || '').trim()
    if (!tok) return ''
    return `${window.location.origin}/share/${tok}`
  }, [meta])

  const create = async () => {
    setIsCreating(true)
    setError(null)
    setMeta(null)
    try {
      const expiresInS = secondsForPreset(preset)
      const res = await shareApi.createShareLink({
        itemType,
        itemId,
        expiresInS,
        password: password.trim(),
      })
      setMeta(res as any)
    } catch (e) {
      setError(e)
    } finally {
      setIsCreating(false)
    }
  }

  const copy = async () => {
    if (!shareUrl) return
    const ok = await copyToClipboard(shareUrl)
    setCopied(ok)
    if (ok) window.setTimeout(() => setCopied(false), 1200)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="aurora-share-link-dialog sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <LinkIcon className="h-4 w-4" />
            生成分享链接
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {title && <div className="text-sm text-muted-foreground">对象：{title}</div>}

          {Boolean(error) && <ErrorNotice error={error} />}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <div className="text-sm font-medium">有效期</div>
              <Select value={preset} onValueChange={setPreset}>
                <SelectTrigger className="aurora-shared-input">
                  <SelectValue placeholder="选择有效期" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1h">1 小时</SelectItem>
                  <SelectItem value="1d">1 天</SelectItem>
                  <SelectItem value="7d">7 天（推荐）</SelectItem>
                  <SelectItem value="30d">30 天</SelectItem>
                  <SelectItem value="never">不过期</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <div className="text-sm font-medium">访问密码（可选）</div>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="留空则无需密码"
                className="aurora-shared-input"
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-2">
            <Button type="button" className="aurora-shared-secondary-action" variant="outline" onClick={() => onOpenChange(false)}>
              关闭
            </Button>
            <Button type="button" className="aurora-shared-primary-action" onClick={create} disabled={isCreating}>
              {isCreating ? <Loader2 className="h-4 w-4 animate-spin" /> : '生成'}
            </Button>
          </div>

          {shareUrl && (
            <div className="aurora-share-link-result rounded-lg p-3 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium flex items-center gap-2">
                  <QrIcon className="h-4 w-4" />
                  分享链接
                </div>
                <Button type="button" className="aurora-shared-secondary-action" variant="outline" size="sm" onClick={copy}>
                  <Copy className="h-4 w-4 mr-2" />
                  {copied ? '已复制' : '复制'}
                </Button>
              </div>
              <div className="text-xs text-muted-foreground break-all">{shareUrl}</div>
              <div className="aurora-share-link-qr flex items-center justify-center">
                <QrCode text={shareUrl} size={200} className="rounded-md" />
              </div>
              {meta?.expires_at && (
                <div className="text-xs text-muted-foreground">
                  过期时间：{new Date(String(meta.expires_at)).toLocaleString('zh-CN')}
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
