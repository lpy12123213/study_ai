import { useQuery } from '@tanstack/react-query'
import { wrongbookApi } from '@/api/wrongbook'
import { Markdown } from '@/components/shared/Markdown'

export default function WrongbookPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['wrongbook'],
    queryFn: () => wrongbookApi.list().then((r) => r.data),
  })
  const items = (data?.items ?? []).map((item) => ({
    id: item.question_id,
    content: item.note || item.source_ref?.stem?.toString() || item.question_id,
  }))

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">错题本</h1>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.id} className="border rounded-lg p-4 bg-card">
            <Markdown content={item.content} />
          </div>
        ))}
      </div>
    </div>
  )
}
