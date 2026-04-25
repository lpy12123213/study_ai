import { useQuery } from '@tanstack/react-query'
import { annotationsApi } from '@/api/annotations'
import { MarkdownRenderer } from '@/components/MarkdownRenderer'

export default function AnnotationsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['annotations'],
    queryFn: () => annotationsApi.list().then((r) => r.data),
  })
  const items: { id: string; content: string; source: string }[] = data?.annotations ?? data ?? []

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">批注</h1>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.id} className="border rounded-lg p-4 bg-card space-y-1">
            <div className="text-xs text-muted-foreground">{item.source}</div>
            <MarkdownRenderer content={item.content} />
          </div>
        ))}
      </div>
    </div>
  )
}
