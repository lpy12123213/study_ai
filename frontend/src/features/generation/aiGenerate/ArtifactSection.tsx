import { RotateCcw, UnlockKeyhole, LockKeyhole } from 'lucide-react'
import { QuestionContent } from '@/components/shared/QuestionContent'
import { RichTextarea } from '@/components/shared/RichTextarea'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { AiGenerateSectionState } from '@/features/generation/aiGenerate/types'

function statusLabel(status: AiGenerateSectionState['status']): string {
  if (status === 'streaming') return '生成中'
  if (status === 'done') return '已完成'
  if (status === 'failed') return '失败'
  return '待生成'
}

function statusVariant(status: AiGenerateSectionState['status']): 'secondary' | 'destructive' | 'outline' {
  if (status === 'failed') return 'destructive'
  if (status === 'done' || status === 'streaming') return 'secondary'
  return 'outline'
}

interface ArtifactSectionProps {
  sectionKey: 'stem' | 'answer' | 'analysis'
  section: AiGenerateSectionState
  onChange?: (content: string) => void
  onToggleLock?: () => void
  onRegenerate?: () => void
}

const SECTION_PLACEHOLDERS: Record<ArtifactSectionProps['sectionKey'], string> = {
  stem: '题干中如有公式，请使用可渲染标记，例如：已知函数 \\(f(x)=x^2+1\\)。',
  answer: '答案中的公式同样使用可渲染标记，例如：\\(x=1\\) 或 \\[x^2-1=0\\]。',
  analysis: '解析过程请保持可读，并把推导公式写成可渲染标记。',
}

export function ArtifactSection(props: ArtifactSectionProps) {
  const { sectionKey, section, onChange, onToggleLock, onRegenerate } = props

  return (
    <div className="rounded-[24px] border border-border/70 bg-background/88 p-4 shadow-sm" data-section={sectionKey}>
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-sm font-semibold">{section.label}</div>
            <Badge
              variant={statusVariant(section.status)}
              className="shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px]"
            >
              {statusLabel(section.status)}
            </Badge>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {section.updatedAt ? <span>{new Date(section.updatedAt).toLocaleTimeString('zh-CN')}</span> : <span>等待产出</span>}
            {section.edited ? <span className="font-medium text-amber-700 dark:text-amber-300">已手动调整</span> : null}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 xl:justify-end">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="rounded-full whitespace-nowrap"
            onClick={onToggleLock}
          >
            {section.locked ? <LockKeyhole className="h-3.5 w-3.5" /> : <UnlockKeyhole className="h-3.5 w-3.5" />}
            {section.locked ? '已锁定' : '锁定'}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="rounded-full whitespace-nowrap"
            onClick={onRegenerate}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            {`重生成${section.label}`}
          </Button>
        </div>
      </div>

      <div className="mt-4 rounded-[20px] border border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(246,241,231,0.72))] p-4 dark:bg-[linear-gradient(180deg,rgba(24,26,40,0.92),rgba(18,20,30,0.88))]">
        <div className="mb-2 text-xs font-medium uppercase tracking-[0.2em] text-muted-foreground">公式预览</div>
        {section.content ? (
          <QuestionContent content={section.content} className="text-sm leading-7 text-foreground/90" />
        ) : (
          <div className="text-sm text-muted-foreground">内容生成后会在这里按公式排版渲染。</div>
        )}
      </div>

      <RichTextarea
        value={section.content}
        onChange={(content) => onChange?.(content)}
        ariaLabel={section.label}
        debounceMs={0}
        minHeight={132}
        maxHeight={260}
        className={cn(
          'mt-4 rounded-[20px] border-border/70 bg-background/80 shadow-none',
          section.status === 'streaming' && 'border-blue-200 bg-blue-50/40 dark:border-sky-800/60 dark:bg-sky-950/20',
          section.status === 'failed' && 'border-destructive/40 bg-destructive/5'
        )}
        placeholder={SECTION_PLACEHOLDERS[sectionKey]}
      />
    </div>
  )
}
