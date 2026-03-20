import { ScrollArea } from '@/components/ui/scroll-area'
import { QuestionDraftCard } from '@/pages/aiGenerate/QuestionDraftCard'
import type { AiGenerateDraftCard } from '@/pages/aiGenerate/types'

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
