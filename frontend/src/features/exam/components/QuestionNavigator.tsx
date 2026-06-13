import { cn } from '@/lib/utils'
import type { ExamQuestion, SaveExamAnswerRequest } from '@/types/exam'

interface QuestionNavigatorProps {
  questions: ExamQuestion[]
  currentIndex: number
  answers: Record<string, SaveExamAnswerRequest>
  onSelect: (index: number) => void
}

function isAnswered(question: ExamQuestion, answer?: SaveExamAnswerRequest): boolean {
  if (!answer) return Boolean(question.studentAnswer)
  if (answer.selectedOptions?.length) return true
  if (answer.fillBlankText?.trim()) return true
  if (answer.handwritingImagePath?.trim()) return true
  if (answer.textAnswer?.trim()) return true
  return false
}

export function QuestionNavigator({ questions, currentIndex, answers, onSelect }: QuestionNavigatorProps) {
  const answered = questions.filter((q) => isAnswered(q, answers[q.questionId])).length
  const percent = questions.length > 0 ? Math.round((answered / questions.length) * 100) : 0

  return (
    <aside className="aurora-exam-navigator flex h-full min-h-0 w-full flex-col md:w-60">
      <div className="aurora-exam-navigator-head p-4">
        <div className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground">Answer map</div>
        <div className="mt-1 text-sm font-medium">题目导航</div>
        <div className="mt-1 text-xs text-muted-foreground">{answered}/{questions.length} 已答 · {percent}%</div>
      </div>
      <div className="grid grid-cols-5 gap-2 overflow-auto p-4 md:grid-cols-4">
        {questions.map((question, index) => {
          const done = isAnswered(question, answers[question.questionId])
          const active = index === currentIndex
          return (
            <button
              key={question.questionId}
              type="button"
              className={cn(
                'aurora-exam-nav-button flex aspect-square items-center justify-center rounded-md border text-sm font-medium transition-colors',
                done && 'is-done',
                active && 'is-active aurora-exam-focus'
              )}
              onClick={() => onSelect(index)}
            >
              {index + 1}
            </button>
          )
        })}
      </div>
    </aside>
  )
}
