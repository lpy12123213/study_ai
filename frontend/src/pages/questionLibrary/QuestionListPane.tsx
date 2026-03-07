import { Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import type { QuestionLibraryListItem } from '@/api/questionLibrary'

function originLabel(origin: string): string {
  if (origin === 'ai') return 'AI 出题'
  if (origin === 'crawled') return '爬取题'
  return origin || '题目'
}

function scoreClass(score: number | null | undefined): string {
  const s = typeof score === 'number' ? score : null
  if (s === null) return 'text-muted-foreground'
  if (s >= 80) return 'text-emerald-600'
  if (s >= 60) return 'text-amber-600'
  return 'text-rose-600'
}

interface Props {
  items: QuestionLibraryListItem[]
  total: number
  isLoading: boolean
  error: any
  selectedId: string
  onSelect: (questionId: string) => void
}

export function QuestionListPane(props: Props) {
  const { items, total, isLoading, error, selectedId, onSelect } = props

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="p-4 border-b flex items-center justify-between gap-3">
        <div className="text-sm font-medium">题目流</div>
        <div className="text-xs text-muted-foreground">共 {total}</div>
      </div>

      <div className="flex-1 min-h-0">
        {isLoading ? (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
            加载中…
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center text-destructive text-sm px-6 text-center">
            {(error as any)?.message || '加载失败'}
          </div>
        ) : items.length === 0 ? (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            暂无题目
          </div>
        ) : (
          <ScrollArea className="h-full">
            <div className="p-4 space-y-3">
              {items.map((it) => {
                const qid = String(it.question_id || '').trim()
                const isSelected = qid && qid === selectedId
                const score = typeof it.ai_score === 'number' ? it.ai_score : null

                return (
                  <button
                    key={qid}
                    type="button"
                    onClick={() => onSelect(qid)}
                    className={cn(
                      'w-full text-left rounded-lg border p-3 transition-colors hover:bg-muted/30',
                      isSelected && 'border-foreground/40 bg-muted/20'
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <div className="text-sm font-medium truncate">题目 {qid}</div>
                          <Badge variant={it.origin === 'ai' ? 'default' : 'secondary'} className="text-[11px]">
                            {originLabel(it.origin)}
                          </Badge>
                          {it.hidden && (
                            <Badge variant="outline" className="text-[11px]">
                              已隐藏
                            </Badge>
                          )}
                        </div>
                        <div className={cn('text-xs mt-1', scoreClass(score))}>
                          {score === null ? '待评分' : `AI 分数：${score}`}
                        </div>
                      </div>
                    </div>

                    {it.stem && (
                      <div className="mt-2 text-xs text-muted-foreground line-clamp-3">
                        {it.stem}
                      </div>
                    )}

                    {it.ai_summary && (
                      <div className="mt-2 text-xs text-muted-foreground line-clamp-2">
                        {it.ai_summary}
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          </ScrollArea>
        )}
      </div>
    </div>
  )
}

