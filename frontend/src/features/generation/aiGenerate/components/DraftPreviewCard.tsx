import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { RichTextarea } from '@/components/shared/RichTextarea'
import type { QuestionLibraryDraftQuestion } from '@/api/questionLibrary'

export interface DraftPreviewMeta {
  subject: string
  topic: string
  count: number
  previewId: string
}

export interface DraftPreviewCardProps {
  meta: DraftPreviewMeta
  draftQuestions: QuestionLibraryDraftQuestion[]
  onChangeDraftQuestions: (
    updater: (prev: QuestionLibraryDraftQuestion[]) => QuestionLibraryDraftQuestion[]
  ) => void
  previewError: string | null
  isCommitting: boolean
  isDiscarding: boolean
  onCommit: () => void
  onDiscard: () => void
}

export function DraftPreviewCard({
  meta,
  draftQuestions,
  onChangeDraftQuestions,
  previewError,
  isCommitting,
  isDiscarding,
  onCommit,
  onDiscard,
}: DraftPreviewCardProps) {
  const keptCount = draftQuestions.filter((q) => q.keep).length

  const updateQuestion = (questionId: string, patch: Partial<QuestionLibraryDraftQuestion>) => {
    onChangeDraftQuestions((prev) =>
      prev.map((it) => (it.question_id === questionId ? { ...it, ...patch } : it))
    )
  }

  return (
    <Card className="aurora-ai-draft overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">Review chamber</div>
            <CardTitle className="text-base">待审核草稿</CardTitle>
            <div className="text-xs text-muted-foreground mt-1">
              {meta.subject} · {meta.topic} · {meta.count} 题 · {meta.previewId}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isCommitting || isDiscarding}
              onClick={onDiscard}
            >
              {isDiscarding ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              丢弃
            </Button>
            <Button
              type="button"
              variant="default"
              size="sm"
              disabled={isCommitting || isDiscarding || keptCount === 0}
              onClick={onCommit}
            >
              {isCommitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
              入库选中 ({keptCount})
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {previewError && <div className="text-sm text-destructive">{previewError}</div>}

        <div className="space-y-4">
          {draftQuestions.map((q, idx) => (
            <div key={q.question_id} className="aurora-ai-draft-item space-y-3 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">
                  #{idx + 1} · {q.question_id}
                </div>
                <div className="flex items-center gap-2">
                  <div className="text-xs text-muted-foreground select-none">{q.keep ? '保留' : '丢弃'}</div>
                  <Switch
                    checked={Boolean(q.keep)}
                    onCheckedChange={(v: boolean) => updateQuestion(q.question_id, { keep: Boolean(v) })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="md:col-span-3">
                  <div className="mb-2 text-xs text-muted-foreground">题干</div>
                  <RichTextarea
                    value={q.stem}
                    onChange={(stem) => updateQuestion(q.question_id, { stem })}
                    ariaLabel="题干"
                    debounceMs={0}
                    minHeight={92}
                    maxHeight={220}
                  />
                </div>
                <div>
                  <div className="mb-2 text-xs text-muted-foreground">答案</div>
                  <RichTextarea
                    value={q.answer}
                    onChange={(answer) => updateQuestion(q.question_id, { answer })}
                    ariaLabel="答案"
                    debounceMs={0}
                    minHeight={92}
                    maxHeight={220}
                  />
                </div>
                <div className="md:col-span-2">
                  <div className="mb-2 text-xs text-muted-foreground">解析</div>
                  <RichTextarea
                    value={q.analysis}
                    onChange={(analysis) => updateQuestion(q.question_id, { analysis })}
                    ariaLabel="解析"
                    debounceMs={0}
                    minHeight={92}
                    maxHeight={220}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
