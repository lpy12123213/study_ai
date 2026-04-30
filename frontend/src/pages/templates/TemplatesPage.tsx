import { useQuery } from '@tanstack/react-query'
import { templatesApi } from '@/api/templates'

export default function TemplatesPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['templates'],
    queryFn: () => templatesApi.list().then((r) => r.data),
  })
  const templates: { id: string; name: string }[] = data?.templates ?? data ?? []

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">模板管理</h1>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {templates.map((t) => (
          <div key={t.id} className="border rounded-lg p-4 bg-card text-sm font-medium hover:bg-accent/30 cursor-pointer transition-colors">{t.name}</div>
        ))}
      </div>
    </div>
  )
}
