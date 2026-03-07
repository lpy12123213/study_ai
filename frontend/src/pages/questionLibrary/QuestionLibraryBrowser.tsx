import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useSubjects } from '@/hooks/useSubjects'
import { CrawlDialog } from '@/pages/questionLibrary/CrawlDialog'
import { QuestionDetailDialog } from '@/pages/questionLibrary/QuestionDetailDialog'
import { QuestionLibraryCard } from '@/pages/questionLibrary/QuestionLibraryCard'
import { QuestionLibraryFilterBar } from '@/pages/questionLibrary/QuestionLibraryFilterBar'
import { RunPanel } from '@/pages/questionLibrary/RunPanel'
import { useQuestionLibrary } from '@/pages/questionLibrary/hooks/useQuestionLibrary'
import { useQuestionLibraryTasks } from '@/pages/questionLibrary/hooks/useQuestionLibraryTasks'

export function QuestionLibraryBrowser() {
  const { data: subjects } = useSubjects()

  const lib = useQuestionLibrary({
    initialFilters: {
      origin: 'crawled',
      hidden: '0',
      sort: 'updated_at',
      order: 'desc',
    },
  })

  const tasks = useQuestionLibraryTasks({
    filters: lib.filters,
    onDone: async () => {
      await lib.refreshList()
      await lib.refreshDetail()
    },
  })

  const [crawlOpen, setCrawlOpen] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)

  const openDetail = (qid: string) => {
    lib.setSelectedId(qid)
    setDetailOpen(true)
  }

  return (
    <div className="h-full w-full flex flex-col overflow-hidden">
      <div className="px-6 py-4 border-b bg-background">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-lg font-semibold tracking-tight">本地题库</div>
            <div className="text-xs text-muted-foreground">
              爬取题与 AI 题统一入库。本页默认展示爬取题，可切换来源筛选。
            </div>
          </div>

          <div className="flex items-center gap-2">
            {lib.listQuery.isFetching && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                加载中
              </div>
            )}
            <Button type="button" variant="outline" size="sm" onClick={() => setCrawlOpen(true)}>
              爬取入库
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() =>
                tasks.runScore({
                  subject: lib.filters.subject,
                  limit: 50,
                  only_unscored: true,
                })
              }
            >
              手动评分
            </Button>
          </div>
        </div>

        <div className="mt-4">
          <QuestionLibraryFilterBar
            subjects={subjects || []}
            filters={lib.filters}
            onSubjectChange={lib.setSubject}
            onOriginChange={lib.setOrigin}
            onHiddenChange={lib.setHidden}
            onQueryChange={lib.setQuery}
            onSortChange={lib.setSort}
            onOrderChange={lib.setOrder}
            onRefresh={lib.refreshList}
          />
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        {lib.listQuery.isLoading ? (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
            加载中…
          </div>
        ) : lib.listQuery.error ? (
          <div className="h-full flex items-center justify-center text-destructive text-sm px-6 text-center">
            {(lib.listQuery.error as any)?.message || '加载失败'}
          </div>
        ) : lib.items.length === 0 ? (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            暂无题目
          </div>
        ) : (
          <ScrollArea className="h-full">
            <div className="p-6 space-y-4">
              {lib.items.map((it) => (
                <QuestionLibraryCard
                  key={it.question_id}
                  item={it}
                  onOpenDetail={openDetail}
                  onSearchSimilar={(q) => lib.setQuery(q)}
                  onMutated={async () => {
                    await lib.refreshList()
                    await lib.refreshDetail()
                  }}
                />
              ))}
            </div>
          </ScrollArea>
        )}
      </div>

      <RunPanel task={tasks.preferredTask} />

      <CrawlDialog
        open={crawlOpen}
        onOpenChange={setCrawlOpen}
        subject={lib.filters.subject}
        onSubmit={(p) => {
          tasks.runCrawl({
            subject: lib.filters.subject,
            query: p.query,
            difficulty: p.difficulty,
            limit: p.limit,
            max_pages: p.max_pages,
            min_quality_score: p.min_quality_score,
          })
        }}
      />

      <QuestionDetailDialog
        open={detailOpen}
        onOpenChange={(open) => {
          setDetailOpen(open)
          if (!open) lib.setSelectedId('')
        }}
        selectedId={lib.selectedId}
        listItem={lib.selectedItem}
        detail={lib.detail}
        isLoading={lib.detailQuery.isLoading}
        error={lib.detailQuery.error as any}
        onMutated={async () => {
          await lib.refreshList()
          await lib.refreshDetail()
        }}
      />
    </div>
  )
}

