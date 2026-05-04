import { useQuery } from '@tanstack/react-query'
import { annotationsApi } from '@/api/annotations'
import { Markdown } from '@/components/shared/Markdown'

export default function AnnotationsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['annotations'],
    queryFn: () => annotationsApi.list().then((r) => r.data),
  })
  const items = (data?.annotations ?? []).map((item) => ({
    id: String(item.id),
    content: item.content,
    source: item.snippet || item.item_type,
  }))

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">批注</h1>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.id} className="border rounded-lg p-4 bg-card space-y-1">
            <div className="text-xs text-muted-foreground">{item.source}</div>
            <Markdown content={item.content} />
          </div>
        ))}
      </div>
    </div>
  )
}
