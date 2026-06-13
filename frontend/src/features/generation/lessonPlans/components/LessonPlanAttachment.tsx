import { Link } from 'react-router-dom'
import { ArrowRight, BookOpenCheck, Clock } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'

export function LessonPlanAttachment({ lessonPlanId }: { lessonPlanId: string }) {
  const plan = useLessonPlanStore((state) => state.getPlan(lessonPlanId))
  if (!plan) return null

  return (
    <div className="mt-4">
      <Link to={`/lesson-plans/${plan.id}`} className="block group">
        <div className="aurora-lesson-attachment rounded-xl p-4 transition-all hover:border-primary/50">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                  <BookOpenCheck className="h-4 w-4" />
                </div>
                <div className="font-semibold truncate text-foreground">{plan.title}</div>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                <Badge variant="secondary" className="font-normal">
                  {plan.subject}
                </Badge>
                <span>{plan.grade}</span>
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {plan.duration} 分钟
                </span>
              </div>
            </div>
            <div className="self-center opacity-0 group-hover:opacity-100 transition-opacity -translate-x-2 group-hover:translate-x-0 duration-200">
              <Button variant="ghost" size="icon">
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      </Link>
    </div>
  )
}

