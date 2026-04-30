import { useQuery } from '@tanstack/react-query'
import { blueprintsApi } from '@/api/blueprints'

export default function BlueprintPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['blueprints'],
    queryFn: () => blueprintsApi.list().then((r) => r.data),
  })
  const blueprints: { id: string; name: string }[] = data?.blueprints ?? data ?? []

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">蓝图组卷</h1>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="space-y-2">
        {blueprints.map((b) => (
          <div key={b.id} className="border rounded-lg px-4 py-3 bg-card text-sm">{b.name}</div>
        ))}
      </div>
    </div>
  )
}
