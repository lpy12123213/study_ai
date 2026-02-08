import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Clock,
  FileText,
  GraduationCap,
  Printer,
  Target,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { formatDate } from '@/lib/utils'

export default function LessonPlanDetailPage() {
  const { lessonPlanId } = useParams<{ lessonPlanId: string }>()
  const plan = useLessonPlanStore((state) => state.getPlan(lessonPlanId ?? ''))

  const handlePrint = () => {
    window.print()
  }

  if (!plan) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <FileText className="h-12 w-12 text-muted-foreground mb-4" />
        <p className="text-muted-foreground mb-4">教案不存在或已被清理</p>
        <Button asChild variant="outline">
          <Link to="/lesson-plans">返回列表</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-border p-4 glass flex items-center justify-between print:hidden">
        <div className="flex items-center gap-4 min-w-0">
          <Button variant="ghost" size="icon" asChild>
            <Link to="/lesson-plans" aria-label="返回">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div className="min-w-0">
            <h1 className="font-semibold truncate">{plan.title}</h1>
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <Badge variant="secondary">{plan.subject}</Badge>
              <span>{plan.grade}</span>
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {plan.duration} 分钟
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handlePrint}>
            <Printer className="h-4 w-4 mr-2" />
            打印
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="max-w-3xl mx-auto p-6 print:p-0">
          <div className="text-center mb-8 print:mb-4">
            <div className="inline-flex items-center justify-center h-12 w-12 rounded-2xl bg-foreground text-background mb-4">
              <GraduationCap className="h-6 w-6" />
            </div>
            <h1 className="text-2xl font-bold mb-2">{plan.title}</h1>
            <div className="text-muted-foreground">
              {plan.subject} | {plan.grade} | {plan.duration} 分钟 |{' '}
              {formatDate(plan.createdAt)}
            </div>
          </div>

          {plan.objectives?.length > 0 && (
            <Card className="mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="h-5 w-5" />
                  教学目标
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="list-disc pl-5 space-y-1 text-sm leading-6">
                  {plan.objectives.map((obj, idx) => (
                    <li key={idx}>{obj}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>教案内容</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="whitespace-pre-wrap text-sm leading-6">
                {plan.content}
              </div>
            </CardContent>
          </Card>

          <Separator className="my-8 print:hidden" />

          <div className="text-xs text-muted-foreground print:hidden">
            提示：内容展示为纯文本（保留换行）。如后端返回 HTML/Markdown，可再升级渲染器。
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}

