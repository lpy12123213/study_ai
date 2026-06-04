import { Loader2 } from 'lucide-react'
import { useSubjects } from '@/hooks/useSubjects'
import { Button } from '@/components/ui/button'
import { QuestionFilterPane } from '@/features/generation/questionLibrary/QuestionFilterPane'
import { QuestionListPane } from '@/features/generation/questionLibrary/QuestionListPane'
import { QuestionDetailPane } from '@/features/generation/questionLibrary/QuestionDetailPane'
import { QuestionBar } from '@/features/generation/questionLibrary/QuestionBar'
import { useQuestionLibrary } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'
import { useQuestionLibraryTasks } from '@/features/generation/questionLibrary/hooks/useQuestionLibraryTasks'
import { CrawlDialog } from '@/features/generation/questionLibrary/CrawlDialog'
import { GenerateDialog } from '@/features/generation/questionLibrary/GenerateDialog'
import { RunPanel } from '@/features/generation/questionLibrary/RunPanel'
import { useState } from 'react'

export function QuestionLibraryStudio() {
  const { data: subjects } = useSubjects()

  const lib = useQuestionLibrary()
  const tasks = useQuestionLibraryTasks({
    filters: lib.filters,
    onDone: async () => {
      await lib.refreshList()
      await lib.refreshDetail()
    },
  })

  const [crawlOpen, setCrawlOpen] = useState(false)
  const [genOpen, setGenOpen] = useState(false)

  return (
    <div className="h-full w-full flex flex-col overflow-hidden">
      <div className="px-6 py-4 border-b bg-background">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="text-lg font-semibold tracking-tight">本地题库</div>
            <div className="text-xs text-muted-foreground">
              爬取题与 AI 出题统一浏览，可隐藏低分题。
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
            <Button type="button" variant="default" size="sm" onClick={() => setGenOpen(true)}>
              AI 出题
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() =>
                tasks.runScore({
                  subject: lib.filters.subject,
                  limit: 50,
                  batch_size: 50,
                  only_unscored: true,
                })
              }
            >
              思维评分
            </Button>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <div className="flex-1 min-h-0 flex overflow-hidden">
          <div className="w-[280px] shrink-0 border-r bg-background">
            <QuestionFilterPane
              subjects={subjects || []}
              subject={lib.filters.subject}
              onSubjectChange={lib.setSubject}
              origin={lib.filters.origin}
              onOriginChange={lib.setOrigin}
              hidden={lib.filters.hidden}
              onHiddenChange={lib.setHidden}
              q={lib.filters.q}
              onQueryChange={lib.setQuery}
              sort={lib.filters.sort}
              order={lib.filters.order}
              onSortChange={lib.setSort}
              onOrderChange={lib.setOrder}
              onRefresh={lib.refreshList}
            />
          </div>

          <div className="flex-1 min-w-0 border-r bg-background">
            <QuestionListPane
              items={lib.items}
              total={lib.total}
              isLoading={lib.listQuery.isLoading}
              error={lib.listQuery.error as any}
              selectedId={lib.selectedId}
              onSelect={lib.setSelectedId}
            />
          </div>

          <div className="w-[380px] shrink-0 bg-background">
            <QuestionDetailPane
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
        </div>

        <QuestionBar />
        <RunPanel task={tasks.preferredTask} />
      </div>

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

      <GenerateDialog
        open={genOpen}
        onOpenChange={setGenOpen}
        subject={lib.filters.subject}
        onSubmit={(p) => {
          tasks.runGenerate({
            subject: lib.filters.subject,
            topic: p.topic,
            difficulty: p.difficulty,
            question_type: p.question_type,
            count: p.count,
            use_study_archive: p.use_study_archive,
          })
        }}
      />
    </div>
  )
}
