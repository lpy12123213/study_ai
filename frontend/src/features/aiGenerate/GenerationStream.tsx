import { ScrollArea } from '@/components/ui/scroll-area'
import { QuestionDraftCard } from '@/features/aiGenerate/QuestionDraftCard'
import type { AiGenerateDraftCard } from '@/features/aiGenerate/types'

interface GenerationStreamProps {
  sessionId?: string
  drafts: AiGenerateDraftCard[]
  getDraftRef?: (index: number) => (node: HTMLDivElement | null) => void
  onSectionChange?: (questionId: string, sectionKey: keyof AiGenerateDraftCard['sections'], content: string) => void
  onToggleSectionLock?: (questionId: string, sectionKey: keyof AiGenerateDraftCard['sections']) => void
  onRegenerateSection?: (questionId: string, sectionKey: keyof AiGenerateDraftCard['sections']) => void
  onConfirm?: (questionId: string) => void
}

export function GenerationStream(props: GenerationStreamProps) {
  const { drafts, getDraftRef, onConfirm, onRegenerateSection, onSectionChange, onToggleSectionLock, sessionId } = props

  if (drafts.length === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-[24px] border border-dashed border-border bg-background/60 px-6 text-center">
        <div className="max-w-md space-y-2">
          <div className="text-base font-medium text-muted-foreground">暂无草稿</div>
          <div className="text-sm leading-6 text-muted-foreground/80">
            草稿将在生成任务完成后显示。如果刚恢复会话，请稍等片刻加载数据。
          </div>
        </div>
      </div>
    )
  }

  return (
    <ScrollArea className="h-full">
      <div className="space-y-4 p-1">
        {drafts.map((draft, index) => (
          <div key={draft.id} ref={getDraftRef?.(index)}>
            <QuestionDraftCard
              draft={draft}
              sessionId={sessionId}
              onConfirm={() => onConfirm?.(draft.questionId)}
              onRegenerateSection={(sectionKey) => onRegenerateSection?.(draft.questionId, sectionKey)}
              onSectionChange={(sectionKey, content) => onSectionChange?.(draft.questionId, sectionKey, content)}
              onToggleSectionLock={(sectionKey) => onToggleSectionLock?.(draft.questionId, sectionKey)}
            />
          </div>
        ))}
      </div>
    </ScrollArea>
  )
}
