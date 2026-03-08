import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, Loader2, MessageSquareText, FileText, BookOpen } from 'lucide-react'
import { searchAll, type SearchResult } from '@/api/search'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const HL_START = '\u0001'
const HL_END = '\u0002'

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

  const openResult = (r: SearchResult) => {
    if (r.type === 'conversation') {
      navigate(`/chat/${encodeURIComponent(String((r as any).conversation_id))}?mid=${encodeURIComponent(String((r as any).message_id))}&q=${encodeURIComponent(qParam)}`)
      return
    }
    if (r.type === 'paper') {
      const qid = String((r as any).question_id || '').trim()
      const paperId = String((r as any).paper_id || '').trim()
      if (qid) navigate(`/papers/${encodeURIComponent(paperId)}#question-${encodeURIComponent(qid)}`)
      else navigate(`/papers/${encodeURIComponent(paperId)}`)
      return
    }
    if (r.type === 'study_archive') {
      navigate(`/study-archives/${encodeURIComponent(String((r as any).archive_id))}?q=${encodeURIComponent(qParam)}`)
      return
    }
    // Unknown type: no-op
  }

  return (
    <div className="h-full flex flex-col overflow-hidden min-h-0">
      <div className="p-4 border-b border-border flex items-center gap-3">
        <div className="flex items-center gap-2">
          <Search className="h-5 w-5 text-primary" />
          <div className="font-semibold">全文搜索</div>
          {isFetching && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </div>
        <div className="flex-1" />
      </div>

      <div className="p-4 space-y-3 overflow-auto">
        <div className="max-w-3xl mx-auto">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="搜索对话、试卷题干、自学资料…"
              className="pl-9"
            />
          </div>

          {Boolean(error) && (
            <div className="mt-3 rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive">
              搜索失败，请稍后重试。
            </div>
          )}

          {qParam && !isFetching && results.length === 0 && (
            <div className="mt-8 text-sm text-muted-foreground text-center">暂无结果</div>
          )}

          <div className="mt-4 space-y-2">
            {results.map((r, idx) => {
              const info = typeLabel(r.type as any)
              const Icon = info.icon
              const title = String((r as any).title || '')
              const snippet = String((r as any).snippet || '')
              return (
                <button
                  key={`${r.type}-${idx}-${title}`}
                  type="button"
                  onClick={() => openResult(r)}
                  className={cn(
                    'w-full text-left rounded-lg border border-border/60 bg-card px-4 py-3 hover:bg-accent/30 transition-colors',
                  )}
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
