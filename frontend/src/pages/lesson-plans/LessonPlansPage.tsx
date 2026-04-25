import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { lessonPlansApi } from '@/api/lessonPlans'

export default function LessonPlansPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['lesson-plans'],
    queryFn: () => lessonPlansApi.list().then((r) => r.data),
  })
  const plans: { id: string; title: string }[] = data?.plans ?? data ?? []

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">教案管理</h1>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="space-y-2">
        {plans.map((p) => (
          <Link key={p.id} to={`/lesson-plans/${p.id}`} className="block border rounded-lg px-4 py-3 bg-card text-sm hover:bg-accent/30 transition-colors">
            {p.title}
          </Link>
        ))}
      </div>
    </div>
  )
}
