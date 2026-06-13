import { BookX, BrainCircuit, Flame, Radar } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MasteryPanel } from '@/features/wrongbook/components/MasteryPanel'
import { ReviewSession } from '@/features/wrongbook/components/ReviewSession'
import { WrongbookListPanel } from '@/features/wrongbook/components/WrongbookListPanel'
import { useReviewQueue } from '@/features/wrongbook/hooks/useReviewQueue'

const TAB_VALUES = new Set(['list', 'review', 'mastery'])

export default function WrongbookPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const queueQuery = useReviewQueue()
  const dueCount = Number(queueQuery.data?.due_count || 0)
  const requestedTab = searchParams.get('tab') || ''
  const activeTab = TAB_VALUES.has(requestedTab) ? requestedTab : 'list'

  const updateTab = (value: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value === 'list') next.delete('tab')
      else next.set('tab', value)
      return next
    }, { replace: true })
  }

  return (
    <div className="aurora-wrongbook-screen flex h-full flex-col overflow-hidden">
      <div className="sticky top-0 z-10 border-b border-border bg-background/50 p-4 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <div className="flex items-center gap-2 font-semibold">
            <BookX className="h-4 w-4 text-[var(--accent-ai-base)]" />
            错题本
          </div>
          <div className="hidden items-center gap-2 font-mono text-xs text-muted-foreground md:flex">
            <span className="h-2 w-2 rounded-full bg-[var(--accent-brand-base)] shadow-[0_0_12px_rgba(0,240,255,0.45)]" />
            SRS review matrix
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-6xl space-y-6">
          <section className="aurora-wrongbook-hero p-5 md:p-7">
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-end">
              <div>
                <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                  <BrainCircuit className="h-3.5 w-3.5 text-[var(--accent-brand-base)]" />
                  Memory lab
                </div>
                <h1 className="app-display text-4xl text-foreground md:text-5xl">错题复习实验室</h1>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground md:text-base">
                  把薄弱知识点、到期复习和掌握度变化放在同一个暗场控制台里，优先处理最该回炉的题目。
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="aurora-wrongbook-stat p-4">
                  <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                    <span>今日到期</span>
                    <Flame className="h-4 w-4 text-[var(--semantic-warning-base)]" />
                  </div>
                  <div className="mt-3 font-mono text-3xl text-foreground">{dueCount}</div>
                </div>
                <div className="aurora-wrongbook-stat p-4">
                  <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                    <span>模式</span>
                    <Radar className="h-4 w-4 text-[var(--accent-brand-base)]" />
                  </div>
                  <div className="mt-3 font-mono text-3xl text-foreground">3</div>
                  <div className="mt-1 text-xs text-muted-foreground">列表/复习/掌握度</div>
                </div>
              </div>
            </div>
          </section>

          <Tabs value={activeTab} onValueChange={updateTab} className="space-y-4">
            <TabsList className="aurora-wrongbook-tabs">
              <TabsTrigger value="list">错题列表</TabsTrigger>
              <TabsTrigger value="review" className="gap-2">
                今日复习
                {dueCount > 0 && <Badge variant="secondary">{dueCount}</Badge>}
              </TabsTrigger>
              <TabsTrigger value="mastery">掌握度</TabsTrigger>
            </TabsList>

            <TabsContent value="list">
              <WrongbookListPanel />
            </TabsContent>
            <TabsContent value="review">
              <ReviewSession />
            </TabsContent>
            <TabsContent value="mastery">
              <MasteryPanel />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  )
}
