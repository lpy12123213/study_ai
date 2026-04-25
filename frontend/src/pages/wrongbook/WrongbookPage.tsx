import { useQuery } from '@tanstack/react-query'
import { wrongbookApi } from '@/api/wrongbook'
import { MarkdownRenderer } from '@/components/MarkdownRenderer'

export default function WrongbookPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['wrongbook'],
    queryFn: () => wrongbookApi.list().then((r) => r.data),
  })
  const items: { id: string; content: string }[] = data?.items ?? data ?? []

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">错题本</h1>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.id} className="border rounded-lg p-4 bg-card">
            <MarkdownRenderer content={item.content} />
          </div>
        ))}
      </div>
    </div>
  )
}
