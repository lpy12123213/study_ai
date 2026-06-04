import { useMemo, useState } from 'react'
import { Eye, EyeOff, Loader2, ShoppingCart } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { QuestionContent } from '@/components/shared/QuestionContent'
import { cn } from '@/lib/utils'
import {
  hideQuestion,
  unhideQuestion,
  type QuestionLibraryDetailResponse,
  type QuestionLibraryListItem,
} from '@/api/questionLibrary'
import { useQuestionBarStore } from '@/stores/useQuestionBarStore'
import { useNotificationStore } from '@/stores/useNotificationStore'
import { isRecord, readNumber, readString } from '@/lib/record'

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

function safeParseJsonArray(input: string): unknown[] {
  const raw = String(input || '').trim()
  if (!raw) return []
  try {
    const obj: unknown = JSON.parse(raw)
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
  error: unknown
  onMutated: () => void
}

export function QuestionDetailPane(props: Props) {
  const { selectedId, listItem, detail, isLoading, error, onMutated } = props
  const [isMutating, setIsMutating] = useState(false)
  const [mutateError, setMutateError] = useState<string | null>(null)
  const addItem = useQuestionBarStore((s) => s.addItem)
  const pushToast = useNotificationStore((s) => s.pushToast)

  const qid = String(selectedId || '').trim()

  const libItem = (detail?.library_item || listItem || null) as QuestionLibraryListItem | null
  const cache = detail?.question_cache || null
  const stemText = String(cache?.stem || libItem?.stem || '').trim()
  const answerText = String(cache?.answer || '').trim()
  const analysisText = String(cache?.analysis || '').trim()

  const dims = useMemo(() => {
    const raw = detail?.library_item?.ai_dimensions_json
    if (typeof raw !== 'string') return []
    return safeParseJsonArray(raw).filter(isRecord).slice(0, 10)
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
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : readString(err, 'message')
      setMutateError(message || '操作失败')
    } finally {
      setIsMutating(false)
    }
  }

  const addToBar = () => {
    if (!qid) return
    setMutateError(null)
    const res = addItem({
      questionId: qid,
      origin: String(libItem?.origin || '').trim(),
      stem: stemText,
      sourceUrl: String(cache?.source_url || libItem?.source_url || '').trim(),
    })
    if (!res.ok) {
      setMutateError(res.error || '加入试题栏失败')
      return
    }
    pushToast({ id: `qb-add-${qid}`, title: '已加入试题栏', status: 'completed' })
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="p-4 border-b flex items-center justify-between gap-3">
        <div className="text-sm font-medium">详情</div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!qid || isMutating || isLoading || !libItem}
            onClick={addToBar}
            className="gap-2"
          >
            <ShoppingCart className="h-4 w-4" />
            加入试题栏
          </Button>
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
            {(error instanceof Error ? error.message : readString(error, 'message')) || '加载失败'}
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
                <div className={cn('text-xs mt-1', depthScoreClass(libItem.thinking_depth_score ?? null))}>
                  {typeof libItem.thinking_depth_score === 'number'
                    ? `思维深度：${libItem.thinking_depth_score}/10`
                    : '思维深度待评'}
                  {libItem.thinking_method_family ? (
                    <span className="ml-2">{libItem.thinking_method_family}</span>
                  ) : null}
                </div>
              </div>

              {mutateError && <div className="text-sm text-destructive">{mutateError}</div>}

              <div className="rounded-lg border p-3">
                <div className="text-xs text-muted-foreground mb-2">题干</div>
                {stemText ? (
                  <QuestionContent content={stemText} className="text-sm" />
                ) : (
                  <div className="text-sm text-muted-foreground">暂无题干</div>
                )}
              </div>

              {(answerText || analysisText) && (
                <div className="rounded-lg border p-3 space-y-3">
                  {answerText && (
                    <div>
                      <div className="text-xs text-muted-foreground mb-2">答案</div>
                      <QuestionContent content={answerText} className="text-sm" />
                    </div>
                  )}
                  {analysisText && (
                    <div>
                      <div className="text-xs text-muted-foreground mb-2">解析</div>
                      <QuestionContent content={analysisText} className="text-sm" />
                    </div>
                  )}
                </div>
              )}

              {(dims.length > 0 || libItem.ai_summary) && (
                <div className="rounded-lg border p-3">
                  <div className="text-xs text-muted-foreground mb-2">AI 评分</div>

                  {dims.length > 0 && (
                    <div className="grid grid-cols-1 gap-2">
                      {dims.map((d, idx) => {
                        const name = readString(d, 'name').trim() || `维度 ${idx + 1}`
                        const score = readNumber(d, 'score', NaN)
                        const comment = readString(d, 'comment').trim()
                        return (
                          <div key={`${name}:${idx}`} className="rounded-md bg-muted/30 p-2">
                            <div className="flex items-center justify-between text-xs">
                              <span className="text-muted-foreground">{name}</span>
                              <span className="font-medium">{Number.isFinite(score) ? `${score}/10` : ''}</span>
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
