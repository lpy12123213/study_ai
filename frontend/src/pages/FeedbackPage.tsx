import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bug, Copy, Loader2, Plus, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { FeedbackDialog } from '@/components/shared/FeedbackDialog'
import { formatDate } from '@/lib/utils'
import * as feedbackApi from '@/api/feedback'

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

function formatStatus(status: string): { label: string; tone: 'default' | 'secondary' | 'destructive' } {
  const s = String(status || '').trim().toLowerCase()
  if (s === 'received') return { label: '已收到', tone: 'secondary' }
  if (s === 'triaged') return { label: '已分诊', tone: 'secondary' }
  if (s === 'in_progress') return { label: '处理中', tone: 'secondary' }
  if (s === 'done') return { label: '已完成', tone: 'default' }
  return { label: status || '未知', tone: 'secondary' }
}

export default function FeedbackPage() {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [q, setQ] = useState('')
  const [copiedId, setCopiedId] = useState<number | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['feedback'],
    queryFn: () => feedbackApi.listFeedback(50),
    staleTime: 10_000,
  })

  const items = useMemo(() => {
    const list = (data || []) as feedbackApi.FeedbackReport[]
    const needle = q.trim().toLowerCase()
    if (!needle) return list
    return list.filter((f) => {
      const title = String(f.title || '').toLowerCase()
      const desc = String(f.description || '').toLowerCase()
      return title.includes(needle) || desc.includes(needle)
    })
  }, [data, q])
  const feedbackStats = useMemo(() => {
    const list = (data || []) as feedbackApi.FeedbackReport[]
    const inProgress = list.filter((item) => String(item.status || '') === 'in_progress').length
    const done = list.filter((item) => String(item.status || '') === 'done').length
    const triaged = list.filter((item) => String(item.status || '') === 'triaged').length
    return [
      { label: '反馈总数', value: `${list.length}` },
      { label: '当前列表', value: `${items.length}` },
      { label: '处理中', value: `${inProgress}` },
      { label: '已分诊', value: `${triaged}` },
      { label: '已完成', value: `${done}` },
    ]
  }, [data, items.length])

  return (
    <div className="aurora-feedback-screen h-full flex flex-col overflow-hidden">
      <div className="aurora-feedback-hero p-4 flex items-center justify-between sticky top-0 z-10">
        <div className="min-w-0">
          <div className="aurora-kicker">
            <Sparkles className="h-3.5 w-3.5" />
            Feedback Signal Station
          </div>
          <div className="mt-2 flex items-center gap-2 font-semibold">
            <Bug className="h-4 w-4 text-primary" />
            反馈信号站
          </div>
          <p className="mt-1 text-xs text-muted-foreground">集中查看问题反馈、处理状态和上下文快照，便于复现和跟踪修复。</p>
        </div>
        <div className="aurora-feedback-stat-grid">
          {feedbackStats.map((item) => (
            <div key={item.label} className="aurora-feedback-stat">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
        <Button type="button" size="sm" onClick={() => setDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          新建反馈
        </Button>
      </div>

      <div className="aurora-feedback-filter p-4">
        <Input className="aurora-feedback-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索标题/描述…" />
      </div>

      <ScrollArea className="flex-1">
        <div className="max-w-4xl mx-auto p-6 space-y-3">
          {error && <ErrorNotice error={error} />}
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          )}

          {!isLoading && !error && items.length === 0 && (
            <Card className="aurora-feedback-empty p-6">
              <div className="text-sm text-muted-foreground">暂无反馈记录。</div>
            </Card>
          )}

          {items.map((f) => {
            const status = formatStatus(String(f.status || ''))
            const ctx = f.context || {}
            return (
              <Card key={f.id} className="aurora-feedback-card p-4" data-status={String(f.status || '')}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{f.title || `反馈 #${f.id}`}</div>
                    <div className="text-xs text-muted-foreground mt-1">
                      #{f.id} · {status.label} · {f.created_at ? formatDate(f.created_at) : '-'}
                    </div>
                  </div>
                  <div className="shrink-0">
                    <span
                      className={
                        status.tone === 'default'
                          ? 'aurora-feedback-status text-xs px-2 py-1 rounded bg-primary/10 text-primary'
                          : status.tone === 'destructive'
                            ? 'aurora-feedback-status text-xs px-2 py-1 rounded bg-destructive/10 text-destructive'
                            : 'aurora-feedback-status text-xs px-2 py-1 rounded bg-muted text-muted-foreground'
                      }
                    >
                      {status.label}
                    </span>
                  </div>
                </div>

                {f.description && <div className="mt-3 whitespace-pre-wrap text-sm">{f.description}</div>}

                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      const ok = await copyToClipboard(JSON.stringify(ctx, null, 2))
                      setCopiedId(ok ? f.id : null)
                      if (ok) window.setTimeout(() => setCopiedId(null), 1200)
                    }}
                  >
                    <Copy className="h-4 w-4 mr-2" />
                    {copiedId === f.id ? '已复制上下文' : '复制上下文'}
                  </Button>
                </div>
              </Card>
            )
          })}
        </div>
      </ScrollArea>

      <FeedbackDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  )
}

