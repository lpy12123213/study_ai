import { useMemo, useState } from 'react'
import { Eye, EyeOff, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import {
  hideQuestion,
  unhideQuestion,
  type QuestionLibraryDetailResponse,
  type QuestionLibraryListItem,
} from '@/api/questionLibrary'

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

function safeParseJsonArray(input: string): any[] {
  const raw = String(input || '').trim()
  if (!raw) return []
  try {
    const obj = JSON.parse(raw)
    return Array.isArray(obj) ? obj : []
  } catch {
    return []
  }
}

interface Props {
  selectedId: string
  listItem: QuestionLibraryListItem | null
  detail: QuestionLibraryDetailResponse | null
  isLoading: boolean
  error: any
  onMutated: () => void
}

export function QuestionDetailPane(props: Props) {
  const { selectedId, listItem, detail, isLoading, error, onMutated } = props
  const [isMutating, setIsMutating] = useState(false)
  const [mutateError, setMutateError] = useState<string | null>(null)

  const qid = String(selectedId || '').trim()

  const libItem = (detail?.library_item || listItem || null) as QuestionLibraryListItem | null
  const cache = detail?.question_cache || null

  const dims = useMemo(() => {
    const raw = detail?.library_item?.ai_dimensions_json
    if (typeof raw !== 'string') return []
    return safeParseJsonArray(raw)
      .filter((d) => d && typeof d === 'object')
      .slice(0, 10)
  }, [detail])

  const toggleHidden = async () => {
    if (!qid || !libItem) return
    setIsMutating(true)
    setMutateError(null)
    try {
      if (libItem.hidden) {
        await unhideQuestion(qid)
      } else {
        await hideQuestion(qid)
      }
      onMutated()
    } catch (err: any) {
      setMutateError(err?.message || '操作失败')
    } finally {
      setIsMutating(false)
    }
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="p-4 border-b flex items-center justify-between gap-3">
        <div className="text-sm font-medium">详情</div>
        <Button
          type="button"
          variant={libItem?.hidden ? 'secondary' : 'outline'}
          size="sm"
          disabled={!qid || isMutating || isLoading || !libItem}
          onClick={toggleHidden}
          className="gap-2"
        >
          {isMutating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : libItem?.hidden ? (
            <Eye className="h-4 w-4" />
          ) : (
            <EyeOff className="h-4 w-4" />
          )}
          {libItem?.hidden ? '取消隐藏' : '隐藏'}
        </Button>
      </div>

      <div className="flex-1 min-h-0">
        {!qid ? (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm px-6 text-center">
            选择左侧题目查看详情
          </div>
        ) : isLoading ? (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
            加载中…
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center text-destructive text-sm px-6 text-center">
            {(error as any)?.message || '加载失败'}
          </div>
        ) : !libItem ? (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm px-6 text-center">
            未找到题目
          </div>
        ) : (
          <ScrollArea className="h-full">
            <div className="p-4 space-y-4">
              <div>
                <div className="flex items-center gap-2">
                  <div className="text-sm font-semibold">题目 {qid}</div>
                  <Badge variant={libItem.origin === 'ai' ? 'default' : 'secondary'} className="text-[11px]">
                    {originLabel(libItem.origin)}
                  </Badge>
                  {libItem.hidden && (
                    <Badge variant="outline" className="text-[11px]">
                      已隐藏
                    </Badge>
                  )}
                </div>
                <div className={cn('text-xs mt-1', scoreClass(libItem.ai_score ?? null))}>
                  {typeof libItem.ai_score === 'number' ? `AI 分数：${libItem.ai_score}` : '待评分'}
                  {libItem.ai_verdict ? <span className="ml-2">({libItem.ai_verdict})</span> : null}
                </div>
              </div>

              {mutateError && <div className="text-sm text-destructive">{mutateError}</div>}

              <div className="rounded-lg border p-3">
                <div className="text-xs text-muted-foreground mb-2">题干</div>
                <div className="text-sm whitespace-pre-wrap leading-relaxed">
                  {String(cache?.stem || libItem.stem || '').trim() || '暂无题干'}
                </div>
              </div>

              {libItem.origin === 'ai' && (
                <div className="rounded-lg border p-3 space-y-3">
                  <div>
                    <div className="text-xs text-muted-foreground mb-2">答案</div>
                    <div className="text-sm whitespace-pre-wrap leading-relaxed">
                      {String(cache?.answer || '').trim() || '暂无答案'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground mb-2">解析</div>
                    <div className="text-sm whitespace-pre-wrap leading-relaxed">
                      {String(cache?.analysis || '').trim() || '暂无解析'}
                    </div>
                  </div>
                </div>
              )}

              {(dims.length > 0 || libItem.ai_summary) && (
                <div className="rounded-lg border p-3">
                  <div className="text-xs text-muted-foreground mb-2">AI 评分</div>

                  {dims.length > 0 && (
                    <div className="grid grid-cols-1 gap-2">
                      {dims.map((d, idx) => {
                        const name = String((d as any)?.name || '').trim() || `维度 ${idx + 1}`
                        const score = (d as any)?.score
                        const comment = String((d as any)?.comment || '').trim()
                        return (
                          <div key={`${name}:${idx}`} className="rounded-md bg-muted/30 p-2">
                            <div className="flex items-center justify-between text-xs">
                              <span className="text-muted-foreground">{name}</span>
                              <span className="font-medium">{typeof score === 'number' ? `${score}/10` : ''}</span>
                            </div>
                            {comment && <div className="text-xs text-muted-foreground mt-1 whitespace-pre-wrap">{comment}</div>}
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {libItem.ai_summary && (
                    <div className="mt-3 text-sm text-muted-foreground whitespace-pre-wrap">
                      {libItem.ai_summary}
                    </div>
                  )}
                </div>
              )}
            </div>
          </ScrollArea>
        )}
      </div>
    </div>
  )
}
