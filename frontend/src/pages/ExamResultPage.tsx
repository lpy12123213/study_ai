import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { useExamResult, useExamSession } from '@/hooks/useExam'
import { AnswerReview } from '@/features/exam/components/AnswerReview'

export default function ExamResultPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const { data: session, isLoading: sessionLoading } = useExamSession(sessionId, { includeAnswers: true })
  const { data: result, isLoading: resultLoading, error } = useExamResult(sessionId)

  if (sessionLoading || resultLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !result || !session) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-6 text-center">
        <div className="text-lg font-medium">成绩暂不可用</div>
        <Button asChild variant="outline">
          <Link to="/papers">返回试卷</Link>
        </Button>
      </div>
    )
  }

  const percent = Math.round((result.scoreRatio || 0) * 100)
  const feedback = typeof result.aiFeedback.summary === 'string' ? result.aiFeedback.summary : '已完成自动批改。'

  return (
    <div className="h-full overflow-auto bg-background">
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Button asChild variant="ghost" size="icon">
              <Link to={`/papers/${session.paperId}`}>
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <div>
              <h1 className="text-xl font-semibold">{session.paperName}</h1>
              <p className="text-sm text-muted-foreground">考试成绩</p>
            </div>
          </div>
          <Button asChild variant="outline">
            <Link to={`/exam/${session.sessionId}`}>查看答题页</Link>
          </Button>
        </div>

        <section className="grid gap-4 md:grid-cols-4">
          <div className="rounded-md border bg-card p-4 md:col-span-2">
            <div className="text-sm text-muted-foreground">总分</div>
            <div className="mt-2 text-3xl font-semibold">
              {result.totalScore}/{result.maxScore}
            </div>
            <Progress value={percent} className="mt-4" />
            <div className="mt-2 text-sm text-muted-foreground">{percent}%</div>
          </div>
          <div className="rounded-md border bg-card p-4">
            <div className="text-sm text-muted-foreground">客观题</div>
            <div className="mt-2 text-2xl font-semibold">
              {result.objectiveCorrect}/{result.objectiveTotal}
            </div>
          </div>
          <div className="rounded-md border bg-card p-4">
            <div className="text-sm text-muted-foreground">主观题</div>
            <div className="mt-2 text-2xl font-semibold">
              {result.subjectiveScore}/{result.subjectiveMax}
            </div>
          </div>
        </section>

        <section className="rounded-md border bg-card p-4">
          <div className="mb-2 text-sm font-medium">AI 总评</div>
          <p className="text-sm text-muted-foreground">{feedback}</p>
        </section>

        <AnswerReview questions={session.questions} result={result} />
      </div>
    </div>
  )
}
