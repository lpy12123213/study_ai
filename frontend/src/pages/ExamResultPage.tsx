import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, Loader2, Sparkles, Trophy } from 'lucide-react'
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
  const resultStats = [
    { label: '总分', value: `${result.totalScore}/${result.maxScore}` },
    { label: '得分率', value: `${percent}%` },
    { label: '客观题', value: `${result.objectiveCorrect}/${result.objectiveTotal}` },
    { label: '主观题', value: `${result.subjectiveScore}/${result.subjectiveMax}` },
  ]

  return (
    <div className="aurora-exam-result-screen h-full overflow-auto">
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="aurora-exam-result-topbar flex items-center justify-between gap-3">
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

        <section className="aurora-exam-result-hero">
          <div>
            <div className="aurora-kicker">
              <Sparkles className="h-3.5 w-3.5" />
              Score Debrief Console
            </div>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight">成绩复盘控制台</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              汇总本次考试总分、题型得分和 AI 反馈，并逐题回放作答、得分与批改理由，形成后续错题复习入口。
            </p>
            <div className="aurora-exam-result-score mt-5">
              <Trophy className="h-8 w-8 text-primary" />
              <div>
                <div className="text-4xl font-semibold tracking-tight">{result.totalScore}</div>
                <div className="text-sm text-muted-foreground">/ {result.maxScore} 分 · {percent}%</div>
              </div>
            </div>
            <Progress value={percent} className="mt-4" />
          </div>

          <div className="aurora-exam-result-stat-grid">
            {resultStats.map((item) => (
              <div key={item.label} className="aurora-exam-result-stat">
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="aurora-exam-result-feedback rounded-md p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium">
            <CheckCircle2 className="h-4 w-4 text-primary" />
            AI 总评
          </div>
          <p className="text-sm leading-6 text-muted-foreground">{feedback}</p>
        </section>

        <AnswerReview questions={session.questions} result={result} />
      </div>
    </div>
  )
}
