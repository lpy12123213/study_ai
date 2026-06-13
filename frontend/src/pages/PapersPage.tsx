import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { FileText, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { usePapers } from '@/hooks/usePapers'
import { usePaperMeta } from '@/features/workspace/papers/usePaperMeta'

export default function PapersPage() {
  const { data: papers, isLoading } = usePapers({ limit: 200 })
  const { byId: paperMetaById } = usePaperMeta()

  const paperStats = useMemo(() => {
    const rows = papers || []
    return {
      total: rows.length,
      questions: rows.reduce((sum, paper) => sum + Number(paper.questionCount || 0), 0),
      pinned: rows.filter((paper) => paperMetaById.get(String(paper.id))?.pinned).length,
      starred: rows.filter((paper) => paperMetaById.get(String(paper.id))?.starred).length,
    }
  }, [papers, paperMetaById])

  return (
    <div className="aurora-papers-screen h-full overflow-auto p-6">
      <div className="mx-auto max-w-4xl space-y-6">
        <section className="aurora-papers-hero p-5 md:p-7">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div>
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                <FileText className="h-3.5 w-3.5 text-[var(--accent-brand-base)]" />
                Paper launchpad
              </div>
              <h1 className="app-display text-4xl text-foreground md:text-5xl">试卷发射台</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground md:text-base">
                在左侧列表中搜索、置顶并打开试卷，或新建一份试卷开始组卷。
              </p>
            </div>
            <Button asChild className="gap-2 shadow-sm">
              <Link to="/blueprint">
                <Plus className="h-4 w-4" />
                新建试卷
              </Link>
            </Button>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="aurora-papers-stat p-4">
              <div className="text-xs text-muted-foreground">试卷总数</div>
              <div className="mt-2 font-mono text-3xl text-foreground">{paperStats.total}</div>
            </div>
            <div className="aurora-papers-stat p-4">
              <div className="text-xs text-muted-foreground">题目总数</div>
              <div className="mt-2 font-mono text-3xl text-foreground">{paperStats.questions}</div>
            </div>
            <div className="aurora-papers-stat p-4">
              <div className="text-xs text-muted-foreground">置顶</div>
              <div className="mt-2 font-mono text-3xl text-foreground">{paperStats.pinned}</div>
            </div>
            <div className="aurora-papers-stat p-4">
              <div className="text-xs text-muted-foreground">收藏</div>
              <div className="mt-2 font-mono text-3xl text-foreground">{paperStats.starred}</div>
            </div>
          </div>
        </section>

        {!isLoading && paperStats.total === 0 && (
          <div className="aurora-papers-empty flex flex-col items-center justify-center py-20 text-center">
            <div className="mb-4 flex h-20 w-20 items-center justify-center rounded-full border border-border bg-muted/40">
              <FileText className="h-10 w-10 text-muted-foreground/50" />
            </div>
            <h3 className="text-lg font-medium mb-1">暂无试卷</h3>
            <p className="text-muted-foreground text-sm mb-6 max-w-xs">
              还没有生成任何试卷。点击右上角“新建试卷”开始组卷。
            </p>
            <Button asChild variant="outline">
              <Link to="/blueprint">去组卷</Link>
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
