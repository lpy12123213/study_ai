import { useQuery } from '@tanstack/react-query'
import { exportsApi } from '@/api/exports'

export default function ExportsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['exports'],
    queryFn: () => exportsApi.list().then((r) => r.data),
  })
  const exports_ = (data?.exports ?? []).map((item) => ({
    id: item.filename,
    name: item.filename,
    status: item.file_type,
  }))

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">导出记录</h1>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="space-y-2">
        {exports_.map((e) => (
          <div key={e.id} className="flex items-center gap-3 border rounded-lg px-4 py-3 bg-card text-sm">
            <span className="flex-1">{e.name}</span>
            <span className="text-muted-foreground">{e.status}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
