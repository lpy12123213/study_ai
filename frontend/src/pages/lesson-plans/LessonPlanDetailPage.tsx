import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { lessonPlansApi } from '@/api/lessonPlans'
import { MarkdownRenderer } from '@/components/MarkdownRenderer'

export default function LessonPlanDetailPage() {
  const { id } = useParams()
  const { data, isLoading } = useQuery({
    queryKey: ['lesson-plans', id],
    queryFn: () => lessonPlansApi.get(id!).then((r) => r.data),
  })

  if (isLoading) return <div className="p-6 text-muted-foreground text-sm">加载中...</div>

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">{data?.title}</h1>
      <div className="border rounded-lg p-4 bg-card">
        <MarkdownRenderer content={data?.content ?? ''} />
      </div>
    </div>
  )
}
