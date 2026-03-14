import { ArchiveRestore, CheckCheck, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { AiGenerateDraftCard } from '@/pages/aiGenerate/types'

interface ConfirmedShelfProps {
  drafts: AiGenerateDraftCard[]
  isCommitting: boolean
  isDiscarding: boolean
  onRemove: (questionId: string) => void
  onCommit: () => void
  onDiscard: () => void
}

export function ConfirmedShelf(props: ConfirmedShelfProps) {
  const { drafts, isCommitting, isDiscarding, onRemove, onCommit, onDiscard } = props

  return (
    <Card className="rounded-[28px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(247,241,229,0.92))] shadow-[0_18px_50px_rgba(29,33,44,0.07)]">
      <CardHeader className="flex flex-col gap-4 border-b border-border/60 pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <CardTitle className="text-lg">Confirmed Shelf</CardTitle>
          <div className="mt-1 text-sm text-muted-foreground">
            已确认的题目会暂存在这里，统一入库或撤回。
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" className="rounded-full" onClick={onDiscard} disabled={isDiscarding}>
            <ArchiveRestore className="h-4 w-4" />
            {isDiscarding ? '丢弃中' : '丢弃草稿'}
          </Button>
          <Button type="button" size="sm" className="rounded-full" onClick={onCommit} disabled={drafts.length === 0 || isCommitting}>
            <CheckCheck className="h-4 w-4" />
            {isCommitting ? '入库中' : `全部入库 (${drafts.length})`}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-4 lg:p-6">
        {drafts.length === 0 ? (
          <div className="rounded-[24px] border border-dashed border-border bg-background/60 px-4 py-8 text-center text-sm text-muted-foreground">
            还没有确认题目。你可以先在上方草稿流里逐题确认。
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-3">
            {drafts.map((draft) => (
              <div key={draft.id} className="rounded-[22px] border border-border/70 bg-background/78 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{draft.questionId}</div>
                    <div className="mt-1 text-base font-semibold">{draft.title}</div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="rounded-full"
                    onClick={() => onRemove(draft.questionId)}
                  >
                    <Trash2 className="h-4 w-4" />
                    撤回
                  </Button>
                </div>
                <div className="mt-3 line-clamp-3 text-sm leading-6 text-muted-foreground">
                  {draft.sections.stem.content || '暂无题干'}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
