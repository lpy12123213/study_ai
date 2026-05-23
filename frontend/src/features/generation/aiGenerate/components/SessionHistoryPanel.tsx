import { ChevronDown, History, Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { statusLabel } from '@/features/generation/aiGenerate/studioUtils'

interface SessionHistoryPanelProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  isLoading: boolean
  sessions: any[]
  activeSessionId: string
  onRestore: (sessionId: string) => void
  onArchive: (sessionId: string) => void
}

export function SessionHistoryPanel(props: SessionHistoryPanelProps) {
  return (
    <Card className="overflow-hidden rounded-[30px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.97),rgba(247,242,232,0.93))] shadow-[0_20px_50px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(24,26,40,0.95),rgba(16,18,28,0.94))] dark:shadow-[0_20px_70px_rgba(0,0,0,0.56)]">
      <CardHeader className="border-b border-border/60 pb-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
              <History className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-lg">会话历史</CardTitle>
              <div className="text-sm text-muted-foreground">恢复任意一轮 AI 出题的草稿、流程与 reasoning。</div>
            </div>
          </div>
          <Button type="button" variant="ghost" size="sm" className="rounded-full" onClick={() => props.onOpenChange(!props.open)}>
            <ChevronDown className={`h-4 w-4 transition-transform ${props.open ? '' : '-rotate-90'}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {props.open ? (
          <ScrollArea className="h-[980px]">
            <div className="space-y-3 p-4">
              {props.isLoading ? (
                <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  会话加载中
                </div>
              ) : (props.sessions || []).length === 0 ? (
                <div className="rounded-[22px] border border-dashed border-border bg-background/60 px-4 py-8 text-center text-sm text-muted-foreground">
                  还没有会话历史，先从中间工作台启动一轮出题。
                </div>
              ) : (
                (props.sessions || []).map((item: any) => {
                  const sid = String(item.session_id || '').trim()
                  const selected = sid === props.activeSessionId
                  return (
                    <div
                      key={sid}
                      className={`rounded-[24px] border p-4 transition-colors ${
                        selected
                          ? 'border-amber-300 bg-amber-50/80 dark:border-amber-700/60 dark:bg-amber-950/20'
                          : 'border-border/70 bg-background/80'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-xs uppercase tracking-[0.22em] text-muted-foreground">{item.subject || '未命名学科'}</div>
                          <div className="mt-1 truncate text-sm font-medium">{item.topic || '未命名主题'}</div>
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <Badge variant="outline" className="rounded-full">
                              {statusLabel(String(item.status || ''))}
                            </Badge>
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <Badge variant="outline" className="rounded-full">
                              {String(item.mode || 'standard') === 'infinite' ? '无限模式' : '标准模式'}
                            </Badge>
                            <Badge variant="outline" className="rounded-full">
                              {Number(item.count || 0)} 题
                            </Badge>
                            <Badge variant="outline" className="rounded-full">
                              reasoning {Number(item.reasoning_blocks_count || 0)}
                            </Badge>
                          </div>
                          <div className="mt-4 flex flex-wrap items-center gap-2">
                            <Button type="button" size="sm" className="rounded-full" onClick={() => props.onRestore(sid)}>
                              恢复会话
                            </Button>
                            <Button type="button" variant="outline" size="sm" className="rounded-full" onClick={() => props.onArchive(sid)}>
                              归档
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </ScrollArea>
        ) : null}
      </CardContent>
    </Card>
  )
}

