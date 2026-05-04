import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { papersApi } from '@/api/papers'
import { Markdown } from '@/components/shared/Markdown'

export default function PaperDetailPage() {
  const { paperId } = useParams()
  const { data, isLoading } = useQuery({
    queryKey: ['papers', paperId],
    queryFn: () => papersApi.get(paperId!).then((r) => r.data),
  })

  if (isLoading) return <div className="text-muted-foreground text-sm">加载中...</div>
  if (!data) return <div className="text-muted-foreground text-sm">未找到试卷</div>

  const content = data.questions
    .map((q, index) => `### ${q.order ?? index + 1}. ${q.type || '题目'}\n\n${q.stem || q.questionId}`)
    .join('\n\n')

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{data.name || '未命名试卷'}</h1>
      <div className="border rounded-lg p-6 bg-card">
        <Markdown content={content} />
      </div>
    </div>
  )
}
