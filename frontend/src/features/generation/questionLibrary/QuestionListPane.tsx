import { useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { QuestionContent } from '@/components/shared/QuestionContent'
import { cn } from '@/lib/utils'
import { getQuestionLibraryItem, type QuestionLibraryListItem } from '@/api/questionLibrary'

function originLabel(origin: string): string {
  if (origin === 'ai') return 'AI 出题'
  if (origin === 'crawled') return '爬取题'
  if (origin === 'media') return '图片/PDF 录入'
  return origin || '题目'
}

function scoreClass(score: number | null | undefined): string {
  const s = typeof score === 'number' ? score : null
  if (s === null) return 'text-muted-foreground'
  if (s >= 80) return 'text-emerald-600'
  if (s >= 60) return 'text-amber-600'
  return 'text-rose-600'
}

function depthScoreClass(score: number | null | undefined): string {
  const s = typeof score === 'number' ? score : null
  if (s === null) return 'text-muted-foreground'
  if (s >= 8) return 'text-emerald-600'
  if (s >= 5) return 'text-amber-600'
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
  const [expandedId, setExpandedId] = useState<string>('')
  const [loadingId, setLoadingId] = useState<string>('')
  const [inlineById, setInlineById] = useState<Record<string, { answer: string; analysis: string }>>({})

  const selected = String(selectedId || '').trim()

  const canExpandById = useMemo(() => {
    const out: Record<string, boolean> = {}
    for (const it of items) {
      const qid = String(it.question_id || '').trim()
      if (!qid) continue
      out[qid] = Boolean(it.has_answer || it.has_analysis)
    }
    return out
  }, [items])

  const handleToggle = async (qid: string) => {
    const id = String(qid || '').trim()
    if (!id) return
    onSelect(id)

    const canExpand = Boolean(canExpandById[id])
    if (!canExpand) return

    if (expandedId === id) {
      setExpandedId('')
      return
    }
    setExpandedId(id)

    if (inlineById[id]) return
    setLoadingId(id)
    try {
      const detail = await getQuestionLibraryItem(id)
      const cache = (detail as any)?.question_cache || null
      const answer = String(cache?.answer || '').trim()
      const analysis = String(cache?.analysis || '').trim()
      setInlineById((prev) => ({ ...prev, [id]: { answer, analysis } }))
      if (!answer && !analysis) {
        setExpandedId('')
      }
    } catch {
      setExpandedId('')
    } finally {
      setLoadingId('')
    }
  }

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
                const isSelected = qid && qid === selected
                const score = typeof it.ai_score === 'number' ? it.ai_score : null
                const depthScore = typeof it.thinking_depth_score === 'number' ? it.thinking_depth_score : null
                const canExpand = Boolean(canExpandById[qid])
                const isExpanded = qid && qid === expandedId

                return (
                  <div
                    key={qid}
                    className={cn(
                      'w-full rounded-lg border transition-colors hover:bg-muted/30',
                      isSelected && 'border-foreground/40 bg-muted/20'
                    )}
                  >
                    <button
                      type="button"
                      className="w-full text-left p-3"
                      onClick={() => void handleToggle(qid)}
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
                          <div className={cn('text-xs mt-1', depthScoreClass(depthScore))}>
                            {depthScore === null ? '思维深度待评' : `思维深度：${depthScore}/10`}
                          </div>
                        </div>
                        {canExpand && (
                          <div className="text-xs text-muted-foreground flex items-center gap-1 shrink-0">
                            {loadingId === qid ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : isExpanded ? (
                              <ChevronUp className="h-3.5 w-3.5" />
                            ) : (
                              <ChevronDown className="h-3.5 w-3.5" />
                            )}
                            <span>{isExpanded ? '收起' : '展开'}</span>
                          </div>
                        )}
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

                    {isExpanded && canExpand && (
                      <div className="px-3 pb-3">
                        <div className="rounded-md border bg-muted/20 p-3 space-y-3">
                          {loadingId === qid && (
                            <div className="text-xs text-muted-foreground flex items-center gap-2">
                              <Loader2 className="h-4 w-4 animate-spin" />
                              加载中…
                            </div>
                          )}
                          {loadingId !== qid && inlineById[qid]?.answer && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-2">答案</div>
                              <QuestionContent content={inlineById[qid].answer} className="text-sm" />
                            </div>
                          )}
                          {loadingId !== qid && inlineById[qid]?.analysis && (
                            <div>
                              <div className="text-xs text-muted-foreground mb-2">解析</div>
                              <QuestionContent content={inlineById[qid].analysis} className="text-sm" />
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </ScrollArea>
        )}
      </div>
    </div>
  )
}

