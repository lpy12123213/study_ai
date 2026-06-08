import { BookX } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MasteryPanel } from '@/features/wrongbook/components/MasteryPanel'
import { ReviewSession } from '@/features/wrongbook/components/ReviewSession'
import { WrongbookListPanel } from '@/features/wrongbook/components/WrongbookListPanel'
import { useReviewQueue } from '@/features/wrongbook/hooks/useReviewQueue'

export default function WrongbookPage() {
  const queueQuery = useReviewQueue()
  const dueCount = Number(queueQuery.data?.due_count || 0)

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-background/80 p-4 backdrop-blur-sm">
        <div className="flex items-center gap-2 font-semibold">
          <BookX className="h-4 w-4 text-primary" />
          错题本
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-5xl">
          <Tabs defaultValue="list" className="space-y-4">
            <TabsList>
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
