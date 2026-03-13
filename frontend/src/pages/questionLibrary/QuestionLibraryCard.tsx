import { useMemo, useState } from 'react'
import { Bookmark, Check, ChevronDown, ChevronUp, CircleHelp, Info, Loader2, MessageSquareWarning, ShoppingCart, Square } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { QuestionContent } from '@/components/shared/QuestionContent'
import { cn } from '@/lib/utils'
import {
  getQuestionLibraryItem,
  starQuestion,
  unstarQuestion,
  type QuestionLibraryListItem,
} from '@/api/questionLibrary'
import { useQuestionBarStore } from '@/stores/useQuestionBarStore'
import { useToastStore } from '@/stores/useToastStore'

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function difficultyLabel(difficulty: string): string {
  const d = String(difficulty || '').trim()
  if (d === '简单') return '容易'
  if (d === '中等') return '适中'
  return d || ''
}

function formatDifficulty(difficulty: string, difficultyValue: unknown): string {
  const label = difficultyLabel(difficulty)
  if (isFiniteNumber(difficultyValue)) {
    const v = Math.max(0, Math.min(1, difficultyValue))
    return `${label || '难度'}(${v.toFixed(2)})`
  }
  return label || ''
}

function safeParseJsonArray(input: string): string[] {
  const raw = String(input || '').trim()
  if (!raw) return []
  try {
    const obj = JSON.parse(raw)
    if (!Array.isArray(obj)) return []
    return obj
      .map((x) => (typeof x === 'string' ? x.trim() : ''))
      .filter((x) => x)
  } catch {
    return []
  }
}

function uniq(items: string[], max: number): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const it of items) {
    const v = it.trim()
    if (!v) continue
    if (seen.has(v)) continue
    seen.add(v)
    out.push(v)
    if (out.length >= max) break
  }
  return out
}

function formatDayLabel(iso: string): string {
  const value = String(iso || '').trim()
  if (!value) return ''
  try {
    const d = new Date(value)
    const now = new Date()
    const sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
    if (sameDay) return '今日'
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  } catch {
    return value.slice(0, 10)
  }
}

function extractSimilarQuery(stem: string): string {
  const raw = String(stem || '').replace(/\s+/g, ' ').trim()
  if (!raw) return ''
  const cleaned = raw.replace(/^[0-9]+[.、\s]+/, '').trim()
  const clipped = cleaned.length > 36 ? cleaned.slice(0, 36) : cleaned
  return clipped.trim()
}

interface Props {
  item: QuestionLibraryListItem
  onOpenDetail: (questionId: string) => void
  onSearchSimilar: (query: string) => void
  onMutated: () => void
  bulk?: {
    enabled: boolean
    selected: boolean
    onToggle: () => void
  }
}

export function QuestionLibraryCard(props: Props) {
  const { item, onOpenDetail, onSearchSimilar, onMutated, bulk } = props

  const [isStarring, setIsStarring] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [inlineOpen, setInlineOpen] = useState(false)
  const [inlineLoading, setInlineLoading] = useState(false)
  const [inlineAnswer, setInlineAnswer] = useState<string>('')
  const [inlineAnalysis, setInlineAnalysis] = useState<string>('')

  const qid = String(item.question_id || '').trim()
  const stem = String(item.stem || '').trim()
  const addItem = useQuestionBarStore((s) => s.addItem)
  const pushToast = useToastStore((s) => s.pushToast)

  const canInlineExpand = useMemo(() => {
    if (item.has_answer || item.has_analysis) return true
    return String(item.origin || '').trim() === 'ai'
  }, [item.has_analysis, item.has_answer, item.origin])

  const tags = useMemo(() => {
    const list: string[] = []
    const kp = String(item.knowledge_point || '').trim()
    if (kp) list.push(kp)
    list.push(...safeParseJsonArray(String(item.knowledge_points_json || '')))
    return uniq(list, 10)
  }, [item.knowledge_point, item.knowledge_points_json])

  const metaLeft = useMemo(() => {
    const parts: string[] = []
    const qtype = String(item.question_type || '').trim()
    if (qtype) parts.push(qtype)
    const diff = formatDifficulty(String(item.difficulty || ''), item.difficulty_value)
    if (diff) parts.push(diff)
    return parts.join(' | ')
  }, [item.difficulty, item.difficulty_value, item.question_type])

  const toggleStar = async () => {
    if (!qid) return
    if (isStarring) return
    setIsStarring(true)
    setActionError(null)
    try {
      if (item.starred) {
        await unstarQuestion(qid)
      } else {
        await starQuestion(qid)
      }
      onMutated()
    } catch (err: any) {
      setActionError(err?.message || '操作失败')
    } finally {
      setIsStarring(false)
    }
  }

  const openSource = () => {
    const url = String(item.source_url || '').trim()
    if (!url) {
      setActionError('暂无来源链接')
      return
    }
    try {
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch {
      setActionError('打开失败')
    }
  }

  const toggleInline = async () => {
    if (!qid) return
    if (!canInlineExpand) return
    setActionError(null)
    setInlineOpen((v) => !v)
    if (inlineOpen) return
    if (inlineAnswer || inlineAnalysis) return

    setInlineLoading(true)
    try {
      const detail = await getQuestionLibraryItem(qid)
      const cache = (detail as any)?.question_cache || null
      const answer = String(cache?.answer || '').trim()
      const analysis = String(cache?.analysis || '').trim()
      setInlineAnswer(answer)
      setInlineAnalysis(analysis)
      if (!answer && !analysis) {
        setInlineOpen(false)
      }
    } catch (err: any) {
      setActionError(err?.message || '加载答案解析失败')
      setInlineOpen(false)
    } finally {
      setInlineLoading(false)
    }
  }

  const addToBar = () => {
    if (!qid) return
    setActionError(null)
    try {
      const res = addItem({
        questionId: qid,
        origin: String(item.origin || '').trim(),
        stem,
        sourceUrl: String(item.source_url || '').trim(),
      })
      if (!res.ok) {
        setActionError(res.error || '加入试题栏失败')
        return
      }
      pushToast({ id: `qb-add-${qid}`, title: '已加入试题栏', status: 'completed' })
    } catch (err: any) {
      setActionError(err?.message || '加入试题栏失败')
    }
  }

  const bulkEnabled = Boolean(bulk?.enabled)
  const bulkSelected = Boolean(bulk?.selected)

  return (
    <div
      className={cn(
        'rounded-xl border bg-background p-4 shadow-sm hover:shadow-md transition-shadow',
        bulkEnabled && bulkSelected && 'ring-2 ring-primary/20 border-primary/40'
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {metaLeft && (
            <span className="font-medium text-foreground/80">
              {metaLeft}
            </span>
          )}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {tags.map((t) => (
                <Badge key={t} variant="secondary" className="text-[11px] font-normal">
                  {t}
                </Badge>
              ))}
            </div>
          )}
        </div>

        {bulkEnabled && bulk && (
          <Button
            type="button"
            variant={bulkSelected ? 'secondary' : 'outline'}
            size="sm"
            className="h-8 px-2 text-xs gap-1 shrink-0"
            onClick={bulk.onToggle}
          >
            {bulkSelected ? <Check className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
            {bulkSelected ? '已选' : '选择'}
          </Button>
        )}
      </div>

      <button type="button" className="mt-3 w-full text-left" onClick={toggleInline} disabled={!qid}>
        {stem ? (
          <QuestionContent content={stem} className={cn('text-sm text-foreground/90', canInlineExpand && 'cursor-pointer')} />
        ) : (
          <div className="text-sm text-muted-foreground">暂无题干</div>
        )}
        {canInlineExpand && (
          <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
            {inlineLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : inlineOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            <span>{inlineOpen ? '收起答案解析' : '展开答案解析'}</span>
          </div>
        )}
      </button>

      {inlineOpen && (inlineAnswer || inlineAnalysis || inlineLoading) && (
        <div className="mt-3 rounded-lg border bg-muted/20 p-3 space-y-3">
          {inlineLoading && (
            <div className="text-xs text-muted-foreground flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          )}
          {!inlineLoading && inlineAnswer && (
            <div>
              <div className="text-xs text-muted-foreground mb-2">答案</div>
              <QuestionContent content={inlineAnswer} className="text-sm" />
            </div>
          )}
          {!inlineLoading && inlineAnalysis && (
            <div>
              <div className="text-xs text-muted-foreground mb-2">解析</div>
              <QuestionContent content={inlineAnalysis} className="text-sm" />
            </div>
          )}
        </div>
      )}

      {actionError && <div className="mt-3 text-sm text-destructive">{actionError}</div>}

      <div className="mt-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {item.updated_at ? <span>{formatDayLabel(String(item.updated_at || ''))}</span> : null}
          {item.date ? <span>· {String(item.date || '').trim()}</span> : null}
          {item.hidden ? <span className="text-amber-600">· 已隐藏</span> : null}
        </div>

        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 px-2 text-xs gap-1"
            onClick={() => {
              const q = extractSimilarQuery(stem)
              if (q) onSearchSimilar(q)
            }}
            disabled={!stem}
          >
            <CircleHelp className="h-3.5 w-3.5" />
            相似题
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 px-2 text-xs gap-1"
            onClick={openSource}
          >
            <MessageSquareWarning className="h-3.5 w-3.5" />
            纠错
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 px-2 text-xs gap-1"
            onClick={() => onOpenDetail(qid)}
          >
            <Info className="h-3.5 w-3.5" />
            详情
          </Button>

          <Button
            type="button"
            variant={item.starred ? 'secondary' : 'ghost'}
            size="sm"
            className="h-8 px-2 text-xs gap-1"
            disabled={isStarring}
            onClick={toggleStar}
            title={item.starred ? '取消收藏' : '收藏'}
          >
            <Bookmark className={cn('h-3.5 w-3.5', item.starred ? 'text-foreground' : 'text-muted-foreground')} />
            收藏
          </Button>

          <Button
            type="button"
            size="sm"
            className="h-8 px-3 text-xs gap-2"
            disabled={!qid}
            onClick={addToBar}
            title="加入试题栏（来源模式会被锁定）"
          >
            <ShoppingCart className="h-4 w-4" />
            加入试题栏
          </Button>
        </div>
      </div>
    </div>
  )
}
