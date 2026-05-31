import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { searchApi, type SearchResult } from '@/api/search'
import { Markdown } from '@/components/shared/Markdown'
import { shouldSubmitOnEnter } from '@/lib/keyboard'

function searchResultId(result: SearchResult, index: number): string {
  if ('conversation_id' in result) return `conversation-${result.conversation_id}-${result.message_id}`
  if ('paper_id' in result) return `paper-${result.paper_id}-${result.question_id}`
  if ('archive_id' in result) return `study-archive-${result.archive_id}`
  return `${result.type}-${String(result.title || index)}`
}

function searchResultContent(result: SearchResult): string {
  return result.snippet || result.title || ''
}

export default function SearchPage() {
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['search', query],
    queryFn: () => searchApi.search({ q: query }).then((r) => r.data),
    enabled: !!query,
  })
  const results = (data?.results ?? []).map((result, index) => ({
    id: searchResultId(result, index),
    content: searchResultContent(result),
    type: result.type,
  }))

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">搜索</h1>
      <div className="flex gap-2">
        <input className="flex-1 border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring" placeholder="搜索..." value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => shouldSubmitOnEnter(e) && setQuery(q)} />
        <button onClick={() => setQuery(q)} className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm">搜索</button>
      </div>
      {isLoading && <div className="text-muted-foreground text-sm">搜索中...</div>}
      <div className="space-y-3">
        {results.map((r) => (
          <div key={r.id} className="border rounded-lg p-4 bg-card">
            <div className="text-xs text-muted-foreground mb-1">{r.type}</div>
            <Markdown content={r.content} />
          </div>
        ))}
      </div>
    </div>
  )
}
