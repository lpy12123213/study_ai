import { CheckCircle2, XCircle } from 'lucide-react'
import { AuthImage } from '@/components/shared/AuthImage'
import { QuestionContent } from '@/components/shared/QuestionContent'
import type { ExamQuestion, ExamResult } from '@/types/exam'

interface AnswerReviewProps {
  questions: ExamQuestion[]
  result: ExamResult
}

export function AnswerReview({ questions, result }: AnswerReviewProps) {
  const breakdownById = new Map(result.breakdown.map((item) => [String(item.question_id || item.questionId || ''), item]))
  return (
    <div className="aurora-exam-review space-y-3">
      {questions.map((question, index) => {
        const item = breakdownById.get(question.questionId) || {}
        const correct = item.is_correct
        const score = Number(item.score || 0)
        const maxScore = Number(item.max_score || question.maxScore || 0)
        const scoreRatio = maxScore > 0 ? Math.round((score / maxScore) * 100) : 0
        return (
          <section key={question.questionId} className="aurora-exam-review-card rounded-md p-4" data-correct={String(correct)}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">第 {index + 1} 题</div>
                <div className="text-xs text-muted-foreground">{scoreRatio}% · {question.questionType || question.type}</div>
              </div>
              <div className="flex items-center gap-2 text-sm">
                {correct === true && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
                {correct === false && <XCircle className="h-4 w-4 text-red-600" />}
                <span className="aurora-exam-review-score">{score}/{maxScore} 分</span>
              </div>
            </div>
            <div className="aurora-exam-review-stem">
              <QuestionContent content={question.stem || ''} />
            </div>
            {question.studentAnswer?.handwritingImageUrl && (
              <AuthImage
                src={question.studentAnswer.handwritingImageUrl}
                alt="手写作答"
                className="mt-3 max-h-80 rounded-md border bg-white object-contain"
              />
            )}
            {question.studentAnswer?.textAnswer && (
              <div className="aurora-exam-review-answer mt-3 rounded-md p-3 text-sm whitespace-pre-wrap">{question.studentAnswer.textAnswer}</div>
            )}
            {typeof item.grading === 'object' && item.grading && 'reasoning' in item.grading && (
              <div className="aurora-exam-review-reason mt-3 text-sm text-muted-foreground">{String(item.grading.reasoning || '')}</div>
            )}
          </section>
        )
      })}
    </div>
  )
}
