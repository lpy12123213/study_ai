import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { QuestionLibraryCard } from '@/features/generation/questionLibrary/QuestionLibraryCard'
import { readString } from '@/lib/record'
import type { useQuestionLibrary } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'

type QuestionLibrary = ReturnType<typeof useQuestionLibrary>

export interface RecentQuestionsSectionProps {
  lib: QuestionLibrary
  total: number
  bulkMode: boolean
  onToggleBulkMode: () => void
  selectedCount: number
  selectedIds: Record<string, boolean>
  onSelectAllOnPage: () => void
  onClearSelection: () => void
  onDeleteSelected: () => void
  isBulkDeleting: boolean
  bulkError: string | null
  onToggleSelected: (qid: string) => void
  onOpenDetail: (qid: string) => void
  onRefreshAfterMutation: () => Promise<void> | void
}

export function RecentQuestionsSection({
  lib,
  total,
  bulkMode,
  onToggleBulkMode,
  selectedCount,
  selectedIds,
  onSelectAllOnPage,
  onClearSelection,
  onDeleteSelected,
  isBulkDeleting,
  bulkError,
  onToggleSelected,
  onOpenDetail,
  onRefreshAfterMutation,
}: RecentQuestionsSectionProps) {
  return (
    <>
      <div className="aurora-ai-recent-header flex items-center justify-between gap-4 p-4">
        <div className="min-w-0">
          <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">Generated stream</div>
          <div className="text-sm font-medium">最近 AI 题目</div>
          <div className="text-xs text-muted-foreground">共 {total}</div>
        </div>
        <div className="flex items-center gap-2">
          <Button type="button" variant={bulkMode ? 'secondary' : 'outline'} size="sm" onClick={onToggleBulkMode}>
            批量删除
          </Button>
          {bulkMode && (
            <>
              <Button type="button" variant="ghost" size="sm" onClick={onSelectAllOnPage} disabled={lib.items.length === 0}>
                全选本页
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={onClearSelection} disabled={selectedCount === 0}>
                清空
              </Button>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={onDeleteSelected}
                disabled={selectedCount === 0 || isBulkDeleting}
                className="gap-2"
              >
                {isBulkDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                删除 ({selectedCount})
              </Button>
            </>
          )}
          <Button type="button" variant="outline" size="sm" onClick={lib.refreshList} disabled={lib.listQuery.isFetching}>
            刷新
          </Button>
        </div>
      </div>

      {bulkError && <div className="text-sm text-destructive">{bulkError}</div>}

      {lib.listQuery.isLoading ? (
        <div className="flex items-center justify-center text-muted-foreground text-sm py-10">
          <Loader2 className="h-4 w-4 animate-spin mr-2" />
          加载中…
        </div>
      ) : lib.listQuery.error ? (
        <div className="text-destructive text-sm py-10 text-center">
          {readString(lib.listQuery.error, 'message') || '加载失败'}
        </div>
      ) : lib.items.length === 0 ? (
        <div className="text-muted-foreground text-sm py-10 text-center">暂无 AI 题目</div>
      ) : (
        <div className="space-y-4">
          {lib.items.map((it) => (
            <QuestionLibraryCard
              key={it.question_id}
              item={it}
              onOpenDetail={onOpenDetail}
              onSearchSimilar={(q) => lib.setQuery(q)}
              onMutated={onRefreshAfterMutation}
              bulk={
                bulkMode
                  ? {
                      enabled: true,
                      selected: Boolean(selectedIds[String(it.question_id || '').trim()]),
                      onToggle: () => onToggleSelected(String(it.question_id || '').trim()),
                    }
                  : undefined
              }
            />
          ))}
        </div>
      )}
    </>
  )
}
