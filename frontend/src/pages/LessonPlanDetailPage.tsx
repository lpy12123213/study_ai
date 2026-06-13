import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Clock,
  FileText,
  GraduationCap,
  Download,
  Printer,
  Target,
  Share2,
  Sparkles,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { getLessonPlan } from '@/api/lessonPlans'
import { formatDate } from '@/lib/utils'
import { downloadObjectUrl } from '@/api/client'
import { APP_BRAND_NAME } from '@/constants/branding'

export default function LessonPlanDetailPage() {
  const { lessonPlanId } = useParams<{ lessonPlanId: string }>()
  const localPlan = useLessonPlanStore((state) => state.getPlan(lessonPlanId ?? ''))
  const savePlan = useLessonPlanStore((state) => state.savePlan)
  const { data: remotePlan, isLoading } = useQuery({
    queryKey: ['lessonPlan', lessonPlanId],
    queryFn: async () => {
      const plan = await getLessonPlan(lessonPlanId!)
      savePlan(plan)
      return plan
    },
    enabled: Boolean(lessonPlanId && !localPlan),
  })
  const plan = localPlan || remotePlan

  const openGeneratedFile = async (resourceUrl: string) => {
    const { objectUrl, revoke } = await downloadObjectUrl(resourceUrl)
    const win = window.open(objectUrl, '_blank', 'noopener,noreferrer')
    if (!win) {
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = ''
      a.click()
    }
    window.setTimeout(revoke, 60_000)
  }

  const handlePrint = () => {
    window.print()
  }

  if (!plan) {
    return (
      <div className="aurora-lesson-detail-screen flex flex-col items-center justify-center h-full p-6 text-center">
        <div className="aurora-lesson-detail-empty-icon h-16 w-16 rounded-full flex items-center justify-center mb-4">
           <FileText className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-medium mb-2">{isLoading ? '正在加载教案' : '未找到教案'}</h3>
        <p className="text-muted-foreground mb-6">{isLoading ? '正在从服务端拉取教案详情。' : '该教案可能已被删除或不存在'}</p>
        <Button asChild variant="outline">
          <Link to="/lesson-plans">返回列表</Link>
        </Button>
      </div>
    )
  }

  const detailStats = [
    { label: '学科', value: plan.subject || '未设置' },
    { label: '年级', value: plan.grade || '未设置' },
    { label: '课时', value: `${plan.duration} 分钟` },
    { label: '目标数', value: `${plan.objectives?.length || 0}` },
  ]
  const downloadStats = [
    { label: '可编辑文档', value: plan.mdUrl ? '已生成' : '未生成' },
    { label: 'PDF', value: plan.pdfUrl ? '已生成' : '未生成' },
  ]

  return (
    <div className="aurora-lesson-detail-screen h-full flex flex-col">
      <div className="aurora-lesson-detail-topbar p-4 flex items-center justify-between sticky top-0 z-10 print:hidden">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild className="rounded-full">
            <Link to="/lesson-plans" aria-label="返回">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div className="hidden sm:block">
            <h1 className="font-semibold text-sm">教案详情</h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handlePrint}>
            <Printer className="h-4 w-4 mr-2" />
            打印
          </Button>
          <Button variant="default" size="sm">
            <Share2 className="h-4 w-4 mr-2" />
            分享
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="max-w-5xl mx-auto p-8 print:p-0">
          <section className="aurora-lesson-detail-hero mb-8 print:mb-6">
            <div className="text-center">
              <div className="aurora-lesson-detail-orb mx-auto mb-6 print:hidden">
                <GraduationCap className="h-8 w-8" />
              </div>
              <div className="aurora-kicker justify-center">
                <Sparkles className="h-3.5 w-3.5" />
                Lesson Detail Bridge
              </div>
              <h1 className="mt-4 text-3xl font-bold tracking-tight text-foreground">{plan.title}</h1>
              
              <div className="mt-5 flex flex-wrap items-center justify-center gap-3 text-sm text-muted-foreground">
                <Badge variant="secondary" className="px-3 py-1 text-sm font-normal">{plan.subject}</Badge>
                <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
                <span>{plan.grade}</span>
                <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
                <span className="flex items-center gap-1.5">
                  <Clock className="h-4 w-4" />
                  {plan.duration} 分钟
                </span>
                <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
                <span>{formatDate(plan.createdAt)}</span>
              </div>
            </div>

            <div className="aurora-lesson-detail-stat-grid mt-7">
              {detailStats.map((item) => (
                <div key={item.label} className="aurora-lesson-detail-stat">
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>
          </section>

          <Separator className="my-8 opacity-50" />

          {plan.objectives?.length > 0 && (
            <section className="aurora-lesson-detail-card mb-8">
              <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                <Target className="h-5 w-5 text-primary" />
                教学目标
              </h2>
              <div className="rounded-xl p-6">
                <ul className="space-y-3">
                  {plan.objectives.map((obj, idx) => (
                    <li key={idx} className="flex gap-3 text-sm leading-6 text-foreground/90">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                        {idx + 1}
                      </span>
                      <span>{obj}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}

          <section className="aurora-lesson-detail-card">
            <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <Download className="h-5 w-5 text-primary" />
              下载
            </h2>

            <div className="aurora-lesson-detail-download-panel rounded-xl p-6 flex flex-col gap-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {downloadStats.map((item) => (
                  <div key={item.label} className="aurora-lesson-detail-stat">
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                {plan.mdUrl ? (
                  <Button type="button" onClick={() => void openGeneratedFile(plan.mdUrl!)}>
                    下载可编辑文档
                  </Button>
                ) : (
                  <Button disabled>可编辑文档未生成</Button>
                )}

                {plan.pdfUrl ? (
                  <Button type="button" variant="outline" onClick={() => void openGeneratedFile(plan.pdfUrl!)}>
                    下载 PDF
                  </Button>
                ) : (
                  <Button disabled variant="outline">
                    PDF 未生成
                  </Button>
                )}
              </div>

              <div className="text-xs text-muted-foreground leading-5">
                页面不展示教案正文，仅提供可编辑文档和 PDF 下载链接。
              </div>
            </div>
          </section>

          <div className="mt-12 pt-8 border-t border-border text-center text-xs text-muted-foreground print:hidden">
            生成于 {formatDate(plan.createdAt)} · {APP_BRAND_NAME} 生成
          </div>
        </div>
      </ScrollArea>
    </div>
  )
}
