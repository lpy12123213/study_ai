import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Loader2, RefreshCcw, ShieldCheck, ShieldX } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  approveQuestionLibrarySessionQuestion,
  getQuestionLibrarySession,
  regenerateQuestionLibrarySection,
  rejectQuestionLibrarySessionQuestion,
  reviewQuestionLibrarySessionQuestion,
  type QuestionLibraryDraftQuestion,
} from '@/api/questionLibrary'
import { AuthImage } from '@/components/shared/AuthImage'
import { QuestionContent } from '@/components/shared/QuestionContent'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useNotificationStore } from '@/stores/useNotificationStore'

function reviewLabel(status: string): string {
  const normalized = String(status || '').trim()
  if (normalized === 'approved') return '已通过'
  if (normalized === 'rejected') return '已打回'
  if (normalized === 'confirmed') return '已确认'
  if (normalized === 'committed') return '已入库'
  if (normalized === 'in_review') return '审查中'
  return '待审查'
}

function isTerminalReviewStatus(status: string): boolean {
  const normalized = String(status || '').trim()
  return normalized === 'committed' || normalized === 'rejected'
}

function findNextReviewQuestionId(
  drafts: QuestionLibraryDraftQuestion[] | undefined,
  currentQuestionId: string
): string {
  const items = Array.isArray(drafts) ? drafts : []
  if (items.length === 0) return ''

  const currentIndex = items.findIndex((item) => String(item.question_id || '').trim() === currentQuestionId)
  const startIndex = currentIndex >= 0 ? currentIndex : -1
  for (let offset = 1; offset <= items.length; offset += 1) {
    const item = items[(startIndex + offset) % items.length]
    const questionId = String(item?.question_id || '').trim()
    if (!questionId || questionId === currentQuestionId) continue
    if (!isTerminalReviewStatus(item?.review_status || '')) return questionId
  }
  return ''
}

function ReviewSection(props: {
  title: string
  content: string
  loading?: boolean
  onRegenerate?: () => void
}) {
  const { title, content, loading, onRegenerate } = props

  return (
    <div className="rounded-[24px] border border-border/70 bg-background/80 p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-base font-semibold">{title}</div>
        {onRegenerate ? (
          <Button type="button" variant="outline" size="sm" className="rounded-full" disabled={loading} onClick={onRegenerate}>
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCcw className="h-3.5 w-3.5" />}
            {`重生成${title}`}
          </Button>
        ) : null}
      </div>
      <div className="mt-4 rounded-[20px] border border-border/70 bg-background/90 p-4">
        {content ? (
          <QuestionContent content={content} className="text-sm leading-7 text-foreground/90" />
        ) : (
          <div className="text-sm text-muted-foreground">暂无内容</div>
        )}
      </div>
    </div>
  )
}

function DiagramSection(props: {
  diagrams?: QuestionLibraryDraftQuestion['diagrams']
}) {
  const diagrams = Array.isArray(props.diagrams) ? props.diagrams.filter((item) => item && typeof item.url === 'string') : []
  if (diagrams.length === 0) return null

  return (
    <div className="rounded-[24px] border border-border/70 bg-background/80 p-4">
      <div className="text-base font-semibold">配图</div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {diagrams.map((item, index) => (
          <figure key={`${item.filename || item.url}-${index}`} className="space-y-2">
            <AuthImage
              src={item.url}
              alt={item.alt || 'diagram'}
              className="w-full rounded-2xl border border-border/60 bg-white/70 object-contain shadow-sm dark:bg-white/10"
            />
            {item.caption ? <figcaption className="text-sm text-muted-foreground">{item.caption}</figcaption> : null}
          </figure>
        ))}
      </div>
    </div>
  )
}

export function QuestionReviewPage() {
  const navigate = useNavigate()
  const pushToast = useNotificationStore((state) => state.pushToast)
  const { sessionId = '', questionId = '' } = useParams()
  const sessionIdRef = String(sessionId || '').trim()
  const questionIdRef = String(questionId || '').trim()
  const [question, setQuestion] = useState<QuestionLibraryDraftQuestion | null>(null)
  const [actionLoading, setActionLoading] = useState<'review' | 'approve' | 'reject' | ''>('')
  const [regenerating, setRegenerating] = useState<'stem' | 'answer' | 'analysis' | ''>('')
  const controllerRef = useRef<AbortController | null>(null)

  const sessionQuery = useQuery({
    queryKey: ['questionLibrarySession', sessionIdRef],
    queryFn: () => getQuestionLibrarySession(sessionIdRef),
    enabled: Boolean(sessionIdRef),
    retry: false,
  })

  useEffect(() => {
    const draft =
      sessionQuery.data?.session?.draft_questions?.find(
        (item) => String(item.question_id || '').trim() === questionIdRef
      ) || null
    setQuestion(draft)
  }, [questionIdRef, sessionQuery.data])

  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [])

  const review = question?.review || null
  const previewId = String(sessionQuery.data?.session?.preview_id || '').trim()

  const refreshQuestion = async () => {
    const next = await sessionQuery.refetch()
    const draft =
      next.data?.session?.draft_questions?.find((item) => String(item.question_id || '').trim() === questionIdRef) || null
    setQuestion(draft)
    return next.data?.session || null
  }

  const handleReviewAction = async (action: 'review' | 'approve' | 'reject') => {
    if (!sessionIdRef || !questionIdRef) return
    setActionLoading(action)
    try {
      if (action === 'review') {
        await reviewQuestionLibrarySessionQuestion(sessionIdRef, questionIdRef)
      } else if (action === 'approve') {
        await approveQuestionLibrarySessionQuestion(sessionIdRef, questionIdRef)
      } else {
        await rejectQuestionLibrarySessionQuestion(sessionIdRef, questionIdRef)
      }
      const nextSession = await refreshQuestion()
      if (action !== 'review') {
        const nextQuestionId = findNextReviewQuestionId(nextSession?.draft_questions, questionIdRef)
        if (nextQuestionId) {
          navigate(`/ai-generate/review/${encodeURIComponent(sessionIdRef)}/${encodeURIComponent(nextQuestionId)}`, { replace: true })
        } else {
          navigate(`/ai-generate?session=${encodeURIComponent(sessionIdRef)}`, { replace: true })
        }
      }
      pushToast({
        id: `question-review-${action}-${questionIdRef}`,
        title:
          action === 'review'
            ? '审查意见已生成'
            : action === 'approve'
              ? '该题已通过审核并入库'
              : '该题已打回并切换到下一题',
        status: 'completed',
      })
    } catch (error: any) {
      pushToast({
        id: `question-review-${action}-failed-${questionIdRef}`,
        title: error?.message || '审查动作失败',
        status: 'failed',
      })
    } finally {
      setActionLoading('')
    }
  }

  const handleRegenerate = (sectionKey: 'stem' | 'answer' | 'analysis') => {
    if (!previewId || !question) return
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setRegenerating(sectionKey)
    let appliedDonePayload = false

    regenerateQuestionLibrarySection(
      previewId,
      {
        question_id: question.question_id,
        section_key: sectionKey,
      },
      (event) => {
        if (event.type !== 'done') return
        const content = String(event.data?.content || '').trim()
        appliedDonePayload = true
        setQuestion((prev) => {
          if (!prev) return prev
          return {
            ...prev,
            [sectionKey]: content,
          }
        })
      },
      (error) => {
        pushToast({
          id: `question-review-regenerate-${sectionKey}-${questionIdRef}`,
          title: error.message || '局部重生成失败',
          status: 'failed',
        })
      },
      async () => {
        setRegenerating('')
        if (!appliedDonePayload) {
          await refreshQuestion()
        }
      },
      { signal: controller.signal }
    )
  }

  const dimensions = useMemo(() => review?.dimensions || [], [review])

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto flex max-w-[1320px] flex-col gap-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm text-muted-foreground">AI 出题 / 单题审查</div>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">生成题单题审查页</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" className="rounded-full" onClick={() => navigate(`/ai-generate?session=${encodeURIComponent(sessionIdRef)}`)}>
              <ArrowLeft className="h-4 w-4" />
              返回工作台
            </Button>
            <Button asChild type="button" variant="ghost" className="rounded-full">
              <Link to={`/ai-generate?session=${encodeURIComponent(sessionIdRef)}`}>继续处理会话</Link>
            </Button>
          </div>
        </div>

        {sessionQuery.isLoading ? (
          <Card>
            <CardContent className="flex items-center justify-center py-16 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              会话加载中
            </CardContent>
          </Card>
        ) : !question ? (
          <Card>
            <CardContent className="py-16 text-center text-sm text-muted-foreground">没有找到对应题目或会话已失效。</CardContent>
          </Card>
        ) : (
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_360px]">
            <div className="space-y-6">
              <Card className="rounded-[28px]">
                <CardHeader className="border-b border-border/60 pb-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <CardTitle className="text-lg">题目 {question.question_id}</CardTitle>
                      <div className="mt-1 text-sm text-muted-foreground">在这里逐段审查题干、答案与解析，并可按段局部重生成。</div>
                    </div>
                    <Badge variant="outline" className="rounded-full">
                      {reviewLabel(question.review_status || '')}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4 p-4 lg:p-6">
                  <ReviewSection title="题干" content={question.stem} loading={regenerating === 'stem'} onRegenerate={() => handleRegenerate('stem')} />
                  <DiagramSection diagrams={question.diagrams} />
                  <ReviewSection title="答案" content={question.answer} loading={regenerating === 'answer'} onRegenerate={() => handleRegenerate('answer')} />
                  <ReviewSection title="解析" content={question.analysis} loading={regenerating === 'analysis'} onRegenerate={() => handleRegenerate('analysis')} />
                </CardContent>
              </Card>
            </div>

            <div className="space-y-6">
              <Card className="rounded-[28px]">
                <CardHeader className="border-b border-border/60 pb-4">
                  <div className="flex items-center justify-between gap-3">
                    <CardTitle className="text-lg">审查动作</CardTitle>
                    <Badge variant="outline" className="rounded-full">
                      {reviewLabel(question.review_status || '')}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 p-4 lg:p-6">
                  <Button type="button" className="w-full rounded-full" disabled={!!actionLoading} onClick={() => handleReviewAction('review')}>
                    {actionLoading === 'review' ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                    生成审查意见
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full rounded-full"
                    disabled={!!actionLoading}
                    onClick={() => handleReviewAction('approve')}
                  >
                    {actionLoading === 'approve' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                    通过并入库，下一题
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full rounded-full"
                    disabled={!!actionLoading}
                    onClick={() => handleReviewAction('reject')}
                  >
                    {actionLoading === 'reject' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldX className="h-4 w-4" />}
                    打回并下一题
                  </Button>
                </CardContent>
              </Card>

              <Card className="rounded-[28px]">
                <CardHeader className="border-b border-border/60 pb-4">
                  <CardTitle className="text-lg">结构化审查意见</CardTitle>
                </CardHeader>
                <CardContent className="p-4 lg:p-6">
                  {!review ? (
                    <div className="text-sm text-muted-foreground">还没有审查意见，先点击“生成审查意见”。</div>
                  ) : (
                    <ScrollArea className="h-[520px] pr-3">
                      <div className="space-y-4">
                        <div className="rounded-[20px] border border-border/70 bg-background/80 p-4">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-sm font-medium">结论</div>
                            <Badge variant="outline" className="rounded-full">
                              {review.verdict || '未命名结论'}
                            </Badge>
                          </div>
                          <div className="mt-2 text-sm text-muted-foreground">总分 {Number(review.overall_score || 0)}</div>
                          <div className="mt-2 text-sm leading-6">{review.summary || '暂无总结。'}</div>
                        </div>

                        {dimensions.length > 0 ? (
                          <div className="rounded-[20px] border border-border/70 bg-background/80 p-4">
                            <div className="text-sm font-medium">审查维度</div>
                            <div className="mt-3 space-y-3">
                              {dimensions.map((item) => (
                                <div key={item.name} className="rounded-[16px] border border-border/60 bg-background/80 p-3">
                                  <div className="flex items-center justify-between gap-3">
                                    <div className="font-medium">{item.name}</div>
                                    <Badge variant="outline" className="rounded-full">
                                      {item.score}
                                    </Badge>
                                  </div>
                                  <div className="mt-2 text-sm text-muted-foreground">{item.comment || '暂无说明。'}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}

                        <div className="rounded-[20px] border border-border/70 bg-background/80 p-4">
                          <div className="text-sm font-medium">亮点</div>
                          <div className="mt-3 space-y-2 text-sm">
                            {(review.highlights || []).length > 0 ? (
                              review.highlights.map((item: string, index: number) => <div key={`${item}-${index}`}>- {item}</div>)
                            ) : (
                              <div className="text-muted-foreground">暂无亮点记录。</div>
                            )}
                          </div>
                          <Separator className="my-4" />
                          <div className="text-sm font-medium">问题</div>
                          <div className="mt-3 space-y-2 text-sm">
                            {(review.issues || []).length > 0 ? (
                              review.issues.map((item: string, index: number) => <div key={`${item}-${index}`}>- {item}</div>)
                            ) : (
                              <div className="text-muted-foreground">暂无问题记录。</div>
                            )}
                          </div>
                        </div>
                      </div>
                    </ScrollArea>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default QuestionReviewPage
