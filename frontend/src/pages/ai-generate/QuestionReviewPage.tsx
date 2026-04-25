import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { aiGenerateApi } from '@/api/aiGenerate'
import { MarkdownRenderer } from '@/components/MarkdownRenderer'

export default function QuestionReviewPage() {
  const { sessionId, questionId } = useParams()
  const { data, isLoading } = useQuery({
    queryKey: ['ai-generate', sessionId, questionId],
    queryFn: () => aiGenerateApi.getQuestion(sessionId!, questionId!).then((r) => r.data),
  })

  if (isLoading) return <div className="p-6 text-muted-foreground text-sm">加载中...</div>

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-4">
      <h1 className="text-xl font-semibold">题目审核</h1>
      {data && <div className="border rounded-lg p-4 bg-card"><MarkdownRenderer content={data.content ?? ''} /></div>}
    </div>
  )
}
