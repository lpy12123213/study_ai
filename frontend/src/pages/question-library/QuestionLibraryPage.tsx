import { useQuery } from '@tanstack/react-query'
import { questionLibraryApi } from '@/api/questionLibrary'
import { Markdown } from '@/components/shared/Markdown'
import { useState } from 'react'

export default function QuestionLibraryPage() {
  const [search, setSearch] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['question-library', search],
    queryFn: () => questionLibraryApi.list({ search }).then((r) => r.data),
  })
  const questions = data?.questions ?? []

  return (
    <div className="flex flex-col h-full">
      <div className="border-b p-4 flex gap-2">
        <input
          className="flex-1 border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="搜索题目..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
        {questions.map((q) => (
          <div key={q.id} className="border rounded-lg p-4 bg-card">
            <div className="text-xs text-muted-foreground mb-2">{q.type}</div>
            <Markdown content={q.content} />
          </div>
        ))}
      </div>
    </div>
  )
}
