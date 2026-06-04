import { CheckCircle2, XCircle } from 'lucide-react'
import { Markdown } from '@/components/shared/Markdown'
import type { ExamQuestion, ExamResult } from '@/types/exam'

interface AnswerReviewProps {
  questions: ExamQuestion[]
  result: ExamResult
}

export function AnswerReview({ questions, result }: AnswerReviewProps) {
  const breakdownById = new Map(result.breakdown.map((item) => [String(item.question_id || item.questionId || ''), item]))
  return (
    <div className="space-y-3">
      {questions.map((question, index) => {
        const item = breakdownById.get(question.questionId) || {}
        const correct = item.is_correct
        const score = Number(item.score || 0)
        const maxScore = Number(item.max_score || question.maxScore || 0)
        return (
          <section key={question.questionId} className="rounded-md border bg-card p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="text-sm font-medium">第 {index + 1} 题</div>
              <div className="flex items-center gap-2 text-sm">
                {correct === true && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}
                {correct === false && <XCircle className="h-4 w-4 text-red-600" />}
                <span>{score}/{maxScore} 分</span>
              </div>
            </div>
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <Markdown content={question.stem || ''} />
            </div>
            {question.studentAnswer?.handwritingImageUrl && (
              <img
                src={question.studentAnswer.handwritingImageUrl}
                alt="手写作答"
                className="mt-3 max-h-80 rounded-md border bg-white object-contain"
              />
            )}
            {question.studentAnswer?.textAnswer && (
              <div className="mt-3 rounded-md bg-muted p-3 text-sm whitespace-pre-wrap">{question.studentAnswer.textAnswer}</div>
            )}
            {typeof item.grading === 'object' && item.grading && 'reasoning' in item.grading && (
              <div className="mt-3 text-sm text-muted-foreground">{String(item.grading.reasoning || '')}</div>
            )}
          </section>
        )
      })}
    </div>
  )
}
