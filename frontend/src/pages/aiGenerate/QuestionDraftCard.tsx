import { CheckCircle2, CircleDashed, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ArtifactSection } from '@/pages/aiGenerate/ArtifactSection'
import type { AiGenerateDraftCard, AiGenerateSectionState } from '@/pages/aiGenerate/types'

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

interface QuestionDraftCardProps {
  draft: AiGenerateDraftCard
  onSectionChange?: (sectionKey: keyof AiGenerateDraftCard['sections'], content: string) => void
  onToggleSectionLock?: (sectionKey: keyof AiGenerateDraftCard['sections']) => void
  onRegenerateSection?: (sectionKey: keyof AiGenerateDraftCard['sections']) => void
  onConfirm?: () => void
}

export function QuestionDraftCard(props: QuestionDraftCardProps) {
  const { draft, onConfirm, onRegenerateSection, onSectionChange, onToggleSectionLock } = props
  const status = cardStatusMeta(draft.status)
  const StatusIcon = status.icon

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
            <Button type="button" variant="outline" size="sm" className="rounded-full" onClick={onConfirm}>
              确认入库
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 md:grid-cols-2 2xl:grid-cols-3 lg:p-6">
        {renderSection('stem', draft.sections.stem)}
        {renderSection('answer', draft.sections.answer)}
        {renderSection('analysis', draft.sections.analysis)}
      </CardContent>
    </Card>
  )
}
