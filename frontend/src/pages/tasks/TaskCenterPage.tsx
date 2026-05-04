import { useQuery } from '@tanstack/react-query'
import { tasksApi } from '@/api/tasks'

const STATUS_LABEL: Record<string, string> = { pending: '等待中', running: '运行中', done: '已完成', failed: '失败' }

export default function TaskCenterPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: () => tasksApi.list().then((r) => r.data),
    refetchInterval: 5000,
  })
  const tasks = (data?.tasks ?? []).map((task) => ({
    id: task.id,
    name: task.title || task.task_type,
    status: task.status,
  }))

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">任务中心</h1>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="space-y-2">
        {tasks.map((t) => (
          <div key={t.id} className="flex items-center gap-3 border rounded-lg px-4 py-3 bg-card">
            <span className="flex-1 text-sm">{t.name}</span>
            <span className="text-xs text-muted-foreground">{STATUS_LABEL[t.status] ?? t.status}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
