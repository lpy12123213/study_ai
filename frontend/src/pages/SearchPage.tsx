import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, Loader2, MessageSquareText, FileText, BookOpen, Sparkles } from 'lucide-react'
import { searchAll, type SearchResult } from '@/api/search'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const HL_START = '\u0001'
const HL_END = '\u0002'

function toKeyPart(value: unknown, fallback: number): string | number {
  return typeof value === 'string' || typeof value === 'number' ? value : fallback
}

function resultKey(result: SearchResult, index: number): string {
  let id: string | number = index
  if (result.type === 'conversation') id = toKeyPart(result.message_id || result.conversation_id, index)
  else if (result.type === 'paper') id = toKeyPart(result.question_id || result.paper_id, index)
  else if (result.type === 'question') id = toKeyPart(result.question_id, index)
  else if (result.type === 'study_archive') id = toKeyPart(result.archive_id, index)
  return `${result.type}-${id}`
}

function HighlightedSnippet({ text }: { text: string }) {
  const nodes: ReactNode[] = []
  let i = 0
  let key = 0
  while (i < text.length) {
    const s = text.indexOf(HL_START, i)
    if (s === -1) {
      nodes.push(text.slice(i))
      break
    }
    const e = text.indexOf(HL_END, s + HL_START.length)
    if (e === -1) {
      nodes.push(text.slice(i))
      break
    }
    if (s > i) nodes.push(text.slice(i, s))
    const hit = text.slice(s + HL_START.length, e)
    nodes.push(
      <mark key={`m-${key++}`} className="rounded bg-primary/15 px-0.5 text-foreground">
        {hit}
      </mark>,
    )
    i = e + HL_END.length
  }
  return <span>{nodes}</span>
}

function typeLabel(t: SearchResult['type']): { label: string; icon: typeof Search; tone: 'default' | 'secondary' } {
  if (t === 'conversation') return { label: '对话', icon: MessageSquareText, tone: 'secondary' }
  if (t === 'paper') return { label: '试卷', icon: FileText, tone: 'secondary' }
  if (t === 'question') return { label: '题目', icon: BookOpen, tone: 'secondary' }
  if (t === 'study_archive') return { label: '自学资料', icon: BookOpen, tone: 'secondary' }
  return { label: String(t), icon: Search, tone: 'default' }
}

export default function SearchPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const qParam = (searchParams.get('q') || '').trim()
  const [input, setInput] = useState(qParam)

  useEffect(() => {
    setInput(qParam)
  }, [qParam])

  useEffect(() => {
    const q = input.trim()
    const handle = window.setTimeout(() => {
      if (q === qParam) return
      const next = new URLSearchParams(searchParams)
      if (q) next.set('q', q)
      else next.delete('q')
      setSearchParams(next, { replace: true })
    }, 250)
    return () => window.clearTimeout(handle)
  }, [input, qParam, searchParams, setSearchParams])

  const { data, isFetching, error } = useQuery({
    queryKey: ['search', qParam],
    queryFn: () => searchAll({ q: qParam, limit: 50 }),
    enabled: qParam.length > 0,
    staleTime: 10_000,
  })

  const results = useMemo(() => (data?.results || []) as SearchResult[], [data])
  const resultStats = useMemo(() => {
    const counts = {
      conversation: 0,
      paper: 0,
      question: 0,
      studyArchive: 0,
    }
    for (const item of results) {
      if (item.type === 'conversation') counts.conversation += 1
      if (item.type === 'paper') counts.paper += 1
      if (item.type === 'question') counts.question += 1
      if (item.type === 'study_archive') counts.studyArchive += 1
    }
    return [
      { label: '结果数', value: `${results.length}` },
      { label: '对话', value: `${counts.conversation}` },
      { label: '试卷', value: `${counts.paper}` },
      { label: '资料', value: `${counts.studyArchive}` },
      { label: '题目', value: `${counts.question}` },
    ]
  }, [results])

  const openResult = (r: SearchResult) => {
    if (r.type === 'conversation') {
      navigate(
        `/chat/${encodeURIComponent(String(r.conversation_id))}?mid=${encodeURIComponent(String(r.message_id))}&q=${encodeURIComponent(qParam)}`,
      )
      return
    }
    if (r.type === 'paper') {
      const qid = String(r.question_id || '').trim()
      const paperId = String(r.paper_id || '').trim()
      if (qid) navigate(`/papers/${encodeURIComponent(paperId)}#question-${encodeURIComponent(qid)}`)
      else navigate(`/papers/${encodeURIComponent(paperId)}`)
      return
    }
    if (r.type === 'question') {
      const qid = String(r.question_id || '').trim()
      if (qid) navigate(`/question-library?focus=${encodeURIComponent(qid)}`)
      return
    }
    if (r.type === 'study_archive') {
      navigate(`/study-archives/${encodeURIComponent(String(r.archive_id))}?q=${encodeURIComponent(qParam)}`)
      return
    }
    // Unknown type: no-op
  }

  return (
    <div className="aurora-search-screen h-full flex flex-col overflow-hidden min-h-0">
      <div className="aurora-search-hero p-4 flex items-center gap-4">
        <div className="min-w-0">
          <div className="aurora-kicker">
            <Sparkles className="h-3.5 w-3.5" />
            Global Search Radar
          </div>
          <div className="mt-2 flex items-center gap-2">
            <Search className="h-5 w-5 text-primary" />
            <div className="font-semibold">全文搜索</div>
            {isFetching && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">跨对话、试卷题干、题库和自学资料定位内容，并直接回跳到命中位置。</p>
        </div>
        <div className="aurora-search-stat-grid">
          {resultStats.map((item) => (
            <div key={item.label} className="aurora-search-stat">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      </div>

      <div className="p-4 space-y-3 overflow-auto">
        <div className="max-w-3xl mx-auto">
          <div className="aurora-search-box relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="搜索对话、试卷题干、题库、自学资料…"
              className="aurora-search-input pl-9"
            />
          </div>

          {Boolean(error) && (
            <div className="aurora-search-error mt-3 rounded-lg p-3 text-sm text-destructive">
              搜索失败，请稍后重试。
            </div>
          )}

          {qParam && !isFetching && results.length === 0 && (
            <div className="aurora-search-empty mt-8 text-sm text-muted-foreground text-center">暂无结果</div>
          )}

          <div className="mt-4 space-y-2">
            {results.map((r, idx) => {
              const info = typeLabel(r.type)
              const Icon = info.icon
              const title = String(r.title || '')
              const snippet = String(r.snippet || '')
              return (
                <button
                  key={resultKey(r, idx)}
                  type="button"
                  onClick={() => openResult(r)}
                  className={cn(
                    'aurora-search-result w-full text-left rounded-lg px-4 py-3 transition-colors',
                  )}
                  data-type={r.type}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Icon className="h-4 w-4 text-muted-foreground" />
                        <div className="text-sm font-medium truncate">{title || '(无标题)'}</div>
                        <Badge variant={info.tone}>{info.label}</Badge>
                      </div>
                      {snippet && (
                        <div className="mt-1 text-xs text-muted-foreground leading-5">
                          <HighlightedSnippet text={snippet} />
                        </div>
                      )}
                    </div>
                    <Button type="button" size="sm" variant="ghost" className="shrink-0">
                      打开
                    </Button>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
