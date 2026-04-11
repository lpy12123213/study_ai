import { CheckCircle2, CircleDashed, Eye, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AuthImage } from '@/components/shared/AuthImage'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ArtifactSection } from '@/features/aiGenerate/ArtifactSection'
import { canConfirmDraft } from '@/features/aiGenerate/useAiGenerateSession'
import type { AiGenerateDraftCard, AiGenerateSectionState } from '@/features/aiGenerate/types'

function cardStatusMeta(status: AiGenerateDraftCard['status']): {
  label: string
  icon: typeof CircleDashed
  variant: 'secondary' | 'destructive' | 'outline'
} {
  if (status === 'ready') return { label: '待确认', icon: CheckCircle2, variant: 'secondary' }
  if (status === 'streaming') return { label: '生成中', icon: CircleDashed, variant: 'secondary' }
  if (status === 'failed') return { label: '生成失败', icon: TriangleAlert, variant: 'destructive' }
  return { label: '排队中', icon: CircleDashed, variant: 'outline' }
}

function reviewStatusMeta(status: AiGenerateDraftCard['reviewStatus']): {
  label: string
  variant: 'default' | 'secondary' | 'destructive' | 'outline'
} {
  if (status === 'approved') return { label: '已通过', variant: 'secondary' }
  if (status === 'rejected') return { label: '已打回', variant: 'destructive' }
  if (status === 'confirmed') return { label: '已确认', variant: 'default' }
  if (status === 'committed') return { label: '已入库', variant: 'default' }
  if (status === 'in_review') return { label: '审查中', variant: 'outline' }
  return { label: '待审查', variant: 'outline' }
}

interface QuestionDraftCardProps {
  draft: AiGenerateDraftCard
  sessionId?: string
  onSectionChange?: (sectionKey: keyof AiGenerateDraftCard['sections'], content: string) => void
  onToggleSectionLock?: (sectionKey: keyof AiGenerateDraftCard['sections']) => void
  onRegenerateSection?: (sectionKey: keyof AiGenerateDraftCard['sections']) => void
  onConfirm?: () => void
}

export function QuestionDraftCard(props: QuestionDraftCardProps) {
  const { draft, sessionId, onConfirm, onRegenerateSection, onSectionChange, onToggleSectionLock } = props
  const status = cardStatusMeta(draft.status)
  const StatusIcon = status.icon
  const reviewStatus = reviewStatusMeta(draft.reviewStatus)
  const confirmable = canConfirmDraft(draft)
  const committed = draft.reviewStatus === 'committed'
  const rejected = draft.reviewStatus === 'rejected'
  const confirmLabel = committed ? '已入库' : rejected ? '已打回' : '审核通过并入库'
  const reviewHref = sessionId ? `/ai-generate/review/${encodeURIComponent(sessionId)}/${encodeURIComponent(draft.questionId)}` : ''

  const renderSection = (sectionKey: keyof AiGenerateDraftCard['sections'], section: AiGenerateSectionState) => (
    <ArtifactSection
      key={sectionKey}
      sectionKey={sectionKey}
      section={section}
      onChange={(content) => onSectionChange?.(sectionKey, content)}
      onToggleLock={() => onToggleSectionLock?.(sectionKey)}
      onRegenerate={() => onRegenerateSection?.(sectionKey)}
    />
  )

  return (
    <Card className="rounded-[28px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(251,248,241,0.92))] shadow-[0_20px_60px_rgba(31,35,48,0.08)] dark:bg-[linear-gradient(180deg,rgba(26,28,42,0.94),rgba(18,20,30,0.92))] dark:shadow-[0_20px_80px_rgba(0,0,0,0.55)]">
      <CardHeader className="gap-4 border-b border-border/60 pb-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-muted-foreground">
              <span>{`Draft ${draft.index + 1}`}</span>
              <span>·</span>
              <span>{draft.questionId}</span>
            </div>
            <CardTitle className="text-xl">{draft.title}</CardTitle>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={status.variant} className="rounded-full px-3 py-1 text-xs">
              <StatusIcon className="mr-1 h-3.5 w-3.5" />
              {status.label}
            </Badge>
            <Badge variant={reviewStatus.variant} className="rounded-full px-3 py-1 text-xs">
              {reviewStatus.label}
            </Badge>
            {typeof draft.review?.overallScore === 'number' && draft.reviewStatus !== 'pending_review' ? (
              <Badge variant="outline" className="rounded-full px-3 py-1 text-xs">
                审查分 {draft.review.overallScore}
              </Badge>
            ) : null}
            {reviewHref ? (
              <Button asChild type="button" variant="outline" size="sm" className="rounded-full">
                <Link to={reviewHref}>
                  <Eye className="h-3.5 w-3.5" />
                  进入审查
                </Link>
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="rounded-full"
              disabled={committed || !confirmable}
              onClick={onConfirm}
            >
              {confirmLabel}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 md:grid-cols-2 2xl:grid-cols-3 lg:p-6">
        {renderSection('stem', draft.sections.stem)}
        {renderSection('answer', draft.sections.answer)}
        {renderSection('analysis', draft.sections.analysis)}
        {Array.isArray(draft.diagrams) && draft.diagrams.length > 0 ? (
          <div className="md:col-span-2 2xl:col-span-3">
            <div className="rounded-[22px] border border-border/60 bg-background/60 p-4 shadow-sm">
              <div className="text-xs uppercase tracking-[0.22em] text-muted-foreground">配图</div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {draft.diagrams
                  .filter((item) => item && typeof item.url === 'string')
                  .map((item, idx) => (
                    <figure key={`${item.filename || item.url}-${idx}`} className="space-y-2">
                      <AuthImage
                        src={item.url}
                        alt={item.alt || 'diagram'}
                        className="w-full rounded-2xl border border-border/60 bg-white/70 object-contain shadow-sm dark:bg-white/10"
                      />
                      {item.caption ? (
                        <figcaption className="text-sm text-muted-foreground">{item.caption}</figcaption>
                      ) : null}
                    </figure>
                  ))}
              </div>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
