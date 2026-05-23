import { ArchiveRestore } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { AiGenerateDraftCard } from '@/features/generation/aiGenerate/types'

interface ConfirmedShelfProps {
  drafts: AiGenerateDraftCard[]
  status?: string
  isDiscarding: boolean
  onDiscard: () => void
}

export function ConfirmedShelf(props: ConfirmedShelfProps) {
  const { drafts, status, isDiscarding, onDiscard } = props
  const locked = status === 'committed' || status === 'archived_discarded'

  return (
    <Card className="rounded-[28px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(247,241,229,0.92))] shadow-[0_18px_50px_rgba(29,33,44,0.07)] dark:bg-[linear-gradient(180deg,rgba(26,28,42,0.94),rgba(18,20,30,0.92))] dark:shadow-[0_18px_70px_rgba(0,0,0,0.55)]">
      <CardHeader className="flex flex-col gap-4 border-b border-border/60 pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <CardTitle className="text-lg">已入库题架</CardTitle>
          <div className="mt-1 text-sm text-muted-foreground">
            单题审核通过后会直接进入总库，这里只展示本轮已入库的题目。
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="rounded-full"
            onClick={onDiscard}
            disabled={isDiscarding || locked}
          >
            <ArchiveRestore className="h-4 w-4" />
            {isDiscarding ? '归档中' : '归档草稿'}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-4 lg:p-6">
        {drafts.length === 0 ? (
          <div className="rounded-[24px] border border-dashed border-border bg-background/60 px-4 py-8 text-center text-sm text-muted-foreground">
            还没有已入库题目。可在草稿流直接“审核通过并入库”，也可进入单题审查页逐题处理。
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-3">
            {drafts.map((draft) => (
              <div key={draft.id} className="rounded-[22px] border border-border/70 bg-background/78 p-4">
                <div>
                  <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{draft.questionId}</div>
                  <div className="mt-1 text-base font-semibold">{draft.title}</div>
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
