import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Markdown } from '@/components/shared/Markdown'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { recordReview, type ReviewQueueItem, type ReviewQueueResponse, type ReviewRating } from '@/api/wrongbook'
import { useReviewQueue } from '@/features/wrongbook/hooks/useReviewQueue'

const RATINGS: Array<{ rating: ReviewRating; label: string; tone: 'destructive' | 'outline' | 'secondary' | 'default' }> = [
  { rating: 'again', label: '忘记', tone: 'destructive' },
  { rating: 'hard', label: '模糊', tone: 'outline' },
  { rating: 'good', label: '记得', tone: 'secondary' },
  { rating: 'easy', label: '简单', tone: 'default' },
]

function questionMarkdown(item: ReviewQueueItem): string {
  return item.question?.stem || item.note || item.question_id
}

function answerMarkdown(item: ReviewQueueItem): string {
  const answer = item.question?.answer || ''
  const analysis = item.question?.analysis || ''
  return [answer && `**答案**\n\n${answer}`, analysis && `**解析**\n\n${analysis}`].filter(Boolean).join('\n\n')
}

export function ReviewSession({ subject }: { subject?: string }) {
  const queryClient = useQueryClient()
  const queueQuery = useReviewQueue(subject)
  const [items, setItems] = useState<ReviewQueueItem[]>([])
  const [sessionTotal, setSessionTotal] = useState(0)
  const [completed, setCompleted] = useState(0)
  const [showAnswer, setShowAnswer] = useState(false)
  const [finished, setFinished] = useState(false)

  const queueIds = useMemo(
    () => (queueQuery.data?.items || []).map((item) => item.question_id).join('|'),
    [queueQuery.data?.items],
  )

  useEffect(() => {
    const nextItems = queueQuery.data?.items || []
    if (nextItems.length === 0 && finished) {
      setItems([])
      return
    }
    setItems(nextItems)
    setSessionTotal(nextItems.length)
    setCompleted(0)
    setShowAnswer(false)
    setFinished(false)
  }, [queueIds, queueQuery.data?.items, finished])

  const reviewMutation = useMutation({
    mutationFn: (input: { questionId: string; rating: ReviewRating; isLast: boolean }) =>
      recordReview(input.questionId, input.rating),
    onSuccess: async (_item, variables) => {
      setItems((prev) => prev.slice(1))
      setCompleted((prev) => prev + 1)
      setShowAnswer(false)
      if (variables.isLast) setFinished(true)
      queryClient.setQueriesData<ReviewQueueResponse>({ queryKey: ['wrongbook', 'review'] }, (old) => {
        if (!old) return old
        const nextItems = (old.items || []).filter((item) => item.question_id !== variables.questionId)
        const dueCount = Math.max(0, Number(old.due_count || 0) - 1)
        return {
          ...old,
          items: nextItems,
          due_count: dueCount,
          total: Math.max(0, Number(old.total || 0) - 1),
        }
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['wrongbook', 'mastery'] }),
        queryClient.invalidateQueries({ queryKey: ['wrongbook', 'list'] }),
      ])
    },
  })

  const current = items[0]
  const done = !current && finished && completed > 0

  if (queueQuery.isLoading) {
    return (
      <Card className="p-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载复习队列...
        </div>
      </Card>
    )
  }

  if (queueQuery.error) {
    return <ErrorNotice error={queueQuery.error} />
  }

  if (!current && !done) {
    return (
      <Card className="p-6">
        <div className="text-sm font-medium">今日没有到期错题</div>
        <div className="mt-1 text-sm text-muted-foreground">新的错题加入后会自动进入复习队列。</div>
      </Card>
    )
  }

  if (done) {
    return (
      <Card className="p-6">
        <div className="flex items-center gap-2 text-sm font-medium">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          本轮复习已完成
        </div>
        <div className="mt-1 text-sm text-muted-foreground">已复习 {completed} 道错题。</div>
      </Card>
    )
  }

  const progressTotal = Math.max(sessionTotal, completed + items.length)
  const progressText = `${Math.min(completed + 1, progressTotal)}/${progressTotal}`
  const answer = answerMarkdown(current)

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="break-all font-mono text-sm">{current.question_id}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {current.knowledge_point || current.question?.knowledge_point || '无知识点'} · 掌握度：{current.mastery}
          </div>
        </div>
        <Badge variant="secondary">{progressText}</Badge>
      </div>

      <div className="mt-5 rounded-md border border-border bg-card p-4">
        <Markdown content={questionMarkdown(current)} />
      </div>

      {current.note && current.question?.stem && (
        <div className="mt-3 rounded-md border border-border bg-muted/30 p-3 text-sm text-muted-foreground">
          {current.note}
        </div>
      )}

      {!showAnswer ? (
        <div className="mt-4 flex justify-end">
          <Button type="button" onClick={() => setShowAnswer(true)}>
            显示答案
          </Button>
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <div className="rounded-md border border-border bg-muted/30 p-4">
            {answer ? <Markdown content={answer} /> : <div className="text-sm text-muted-foreground">暂无答案解析。</div>}
          </div>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {RATINGS.map((item) => (
              <Button
                key={item.rating}
                type="button"
                variant={item.tone}
                onClick={() =>
                  reviewMutation.mutate({
                    questionId: current.question_id,
                    rating: item.rating,
                    isLast: items.length <= 1,
                  })
                }
                disabled={reviewMutation.isPending}
              >
                {reviewMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : item.label}
              </Button>
            ))}
          </div>
        </div>
      )}
    </Card>
  )
}
