import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useMasterList } from '@/features/workspace/useMasterList'

export default function StudyArchivesIndexPage() {
  const { data: archives = [], isLoading } = useMasterList('study-archives')

  const subjectCount = useMemo(() => {
    const set = new Set<string>()
    for (const item of archives) {
      const subject = item.title.split(' · ')[0]?.trim()
      if (subject) set.add(subject)
    }
    return set.size
  }, [archives])

  return (
    <div className="aurora-archive-screen h-full overflow-auto p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <section className="aurora-papers-hero p-5 md:p-7">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div>
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                <BookOpen className="h-3.5 w-3.5 text-[var(--accent-brand-base)]" />
                Study archives
              </div>
              <h1 className="app-display text-4xl text-foreground md:text-5xl">学习档案</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground md:text-base">
                自学资料生成后会归档到这里。在左侧列表中搜索并打开档案，可继续导出、克隆或创建学习计划。
              </p>
            </div>
            <Button asChild className="gap-2 shadow-sm">
              <Link to="/study-materials">
                <Plus className="h-4 w-4" />
                生成新资料
              </Link>
            </Button>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <div className="aurora-papers-stat p-4">
              <div className="text-xs text-muted-foreground">档案总数</div>
              <div className="mt-2 font-mono text-3xl text-foreground">{archives.length}</div>
            </div>
            <div className="aurora-papers-stat p-4">
              <div className="text-xs text-muted-foreground">覆盖学科</div>
              <div className="mt-2 font-mono text-3xl text-foreground">{subjectCount}</div>
            </div>
          </div>
        </section>

        {!isLoading && archives.length === 0 && (
          <div className="aurora-papers-empty flex flex-col items-center justify-center py-20 text-center">
            <div className="mb-4 flex h-20 w-20 items-center justify-center rounded-full border border-border bg-muted/40">
              <BookOpen className="h-10 w-10 text-muted-foreground/50" />
            </div>
            <h3 className="text-lg font-medium mb-1">暂无学习档案</h3>
            <p className="text-muted-foreground text-sm mb-6 max-w-xs">
              还没有归档任何自学资料。先去生成一份自学资料吧。
            </p>
            <Button asChild variant="outline">
              <Link to="/study-materials">去生成</Link>
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
