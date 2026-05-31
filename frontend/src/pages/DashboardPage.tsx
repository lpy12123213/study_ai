import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  CheckCircle2,
  Database,
  Download,
  FileText,
  Library,
  Loader2,
  Play,
  Sparkles,
  TimerReset,
  Video,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { downloadObjectUrl } from '@/api/client'
import * as dashboardApi from '@/api/dashboard'
import { DASHBOARD_REFETCH_INTERVAL_MS, useRunningTasks } from '@/hooks/useRunningTasks'

function pct(value?: number): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '--'
  const normalized = numeric > 1 ? numeric : numeric * 100
  return `${Math.round(normalized)}%`
}

function sec(value?: number): string {
  const seconds = Number(value)
  if (!Number.isFinite(seconds)) return '--'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}min`
  return `${Math.round(minutes / 60)}h`
}

function sumTaskTypes(types: Record<string, number> | undefined, needles: string[]) {
  if (!types) return 0
  return Object.entries(types).reduce((sum, [key, value]) => {
    const normalized = key.toLowerCase()
    return needles.some((needle) => normalized.includes(needle)) ? sum + Number(value || 0) : sum
  }, 0)
}

const timelineStages = [
  { label: '规划', color: 'var(--timeline-thinking)', text: '拆解任务意图与资料边界' },
  { label: '检索', color: 'var(--timeline-grep)', text: '检索题库、试卷与学习档案' },
  { label: '阅读', color: 'var(--timeline-read)', text: '读取候选材料并抽取证据' },
  { label: '生成', color: 'var(--timeline-edit)', text: '生成题目、讲义或视频脚本草稿' },
  { label: '完成', color: 'var(--timeline-done)', text: '输出可复查的结果与导出物' },
]

export default function DashboardPage() {
  const [days, setDays] = useState(30)

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['dashboard', days],
    queryFn: () => dashboardApi.getDashboardStats({ days }),
    refetchInterval: DASHBOARD_REFETCH_INTERVAL_MS,
  })

  const { data: runningTasksData } = useRunningTasks()

  const runningTasks = (runningTasksData?.tasks ?? []).slice(0, 5)
  const typeCounts = stats?.tasks_by_type
  const statusRows = Object.entries(stats?.tasks_by_status ?? {})
    .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
    .slice(0, 5)

  const featureCards = [
    {
      title: 'AI 出题',
      description: '从知识点、题库和蓝图生成可审查题目，保留推理与草稿痕迹。',
      path: '/ai-generate',
      icon: Sparkles,
      meta: `${sumTaskTypes(typeCounts, ['generate', 'question']) || '--'} 次任务`,
      stage: '生成',
      color: 'var(--timeline-edit)',
    },
    {
      title: '自学资料',
      description: '把章节、错题和外部资料整理成结构化讲义与复习路径。',
      path: '/study-materials',
      icon: BookOpen,
      meta: `${sumTaskTypes(typeCounts, ['study', 'material']) || '--'} 次任务`,
      stage: '阅读',
      color: 'var(--timeline-read)',
    },
    {
      title: '本地题库',
      description: '集中管理题目、标签、来源与过滤条件，支撑后续生成流程。',
      path: '/question-library',
      icon: Library,
      meta: `${sumTaskTypes(typeCounts, ['library', 'crawl', 'question']) || '--'} 条线索`,
      stage: '检索',
      color: 'var(--timeline-grep)',
    },
  ]

  const summaryCards = [
    { label: '任务总数', value: stats?.tasks_total ?? '--', icon: BarChart3, hint: `近 ${days} 天` },
    { label: '完成率', value: pct(stats?.completion_rate), icon: CheckCircle2, hint: '按任务状态统计' },
    { label: '平均耗时', value: sec(stats?.avg_duration_s), icon: TimerReset, hint: '完成任务均值' },
    { label: '导出文件', value: stats?.exports_total ?? '--', icon: FileText, hint: '试卷与资料归档' },
  ]

  const downloadCsv = async () => {
    const url = `/api/dashboard/export?days=${encodeURIComponent(String(days))}`
    const { objectUrl, revoke, filename } = await downloadObjectUrl(url)
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = filename || `dashboard-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    window.setTimeout(revoke, 60_000)
  }

  return (
    <div className="min-h-full bg-background px-4 py-8 md:px-6 lg:px-8">
      <div className="mx-auto max-w-[1200px] space-y-6">
        <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div className="max-w-3xl">
            <div className="mb-4 inline-flex rounded-full border border-border bg-card px-3 py-1 font-mono text-[11px] font-semibold text-muted-foreground">
              学习工作台
            </div>
            <h1 className="app-display text-3xl text-foreground md:text-5xl">
              把学习任务交给可检查的 AI 流程
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground md:text-base">
              从检索、生成、审查到导出，所有长任务都沿着可复查的时间线推进。界面保留足够留白，
              也保留关键中间产物。
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button asChild className="h-10">
              <Link to="/chat">
                <Play className="h-4 w-4" />
                开始新任务
              </Link>
            </Button>
            <Button asChild variant="outline" className="h-10">
              <Link to="/tasks">
                查看任务中心
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </section>

        <div className="flex flex-wrap items-center justify-between gap-3 border-y border-border py-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />}
            数据窗口：{stats?.from || '--'} → {stats?.to || '--'}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {[7, 30, 90].map((d) => (
              <Button
                key={d}
                type="button"
                size="sm"
                variant="outline"
                className={days === d ? 'bg-foreground text-background hover:bg-foreground/90' : undefined}
                onClick={() => setDays(d)}
              >
                近{d}天
              </Button>
            ))}
            <Button type="button" size="sm" variant="outline" onClick={downloadCsv} disabled={!stats}>
              <Download className="h-4 w-4" />
              导出 CSV
            </Button>
          </div>
        </div>

        {Boolean(error) && <ErrorNotice error={error} />}

        <section className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {summaryCards.map(({ label, value, icon: Icon, hint }) => (
            <Card key={label} className="p-4">
              <div className="flex items-center justify-between gap-3 text-muted-foreground">
                <span className="text-xs">{label}</span>
                <Icon className="h-4 w-4" />
              </div>
              <div className="mt-3 font-mono text-3xl text-foreground">{value}</div>
              <div className="mt-2 text-xs text-muted-foreground">{hint}</div>
            </Card>
          ))}
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-6">
            <div className="grid gap-4 md:grid-cols-3">
              {featureCards.map(({ title, description, path, icon: Icon, meta, stage, color }) => (
                <Link key={path} to={path} className="group app-hairline-card block p-5 transition-colors hover:bg-accent">
                  <div className="flex items-start justify-between gap-4">
                    <span className="flex h-10 w-10 items-center justify-center rounded-md border border-border bg-accent">
                      <Icon className="h-5 w-5 text-foreground" />
                    </span>
                    <span
                      className="rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold text-foreground"
                      style={{ backgroundColor: color }}
                    >
                      {stage}
                    </span>
                  </div>
                  <h2 className="mt-5 text-lg font-medium text-foreground">{title}</h2>
                  <p className="mt-2 min-h-12 text-sm leading-6 text-muted-foreground">{description}</p>
                  <div className="mt-5 flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
                    <span>{meta}</span>
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </div>
                </Link>
              ))}
            </div>

            <Card className="overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
                <div>
                  <div className="font-mono text-xs text-muted-foreground">任务时间线</div>
                  <h2 className="mt-1 text-xl font-medium">可复查的 AI 工作流</h2>
                </div>
                <Button asChild variant="outline" size="sm">
                  <Link to="/deepthink">打开深度解题</Link>
                </Button>
              </div>

              <div className="grid min-h-[420px] bg-card lg:grid-cols-[210px_minmax(0,1fr)_250px]">
                <div className="border-b border-border bg-accent p-4 lg:border-b-0 lg:border-r">
                  <div className="mb-3 font-mono text-xs text-muted-foreground">资料来源</div>
                  {['错题本 / 代数', '本地题库 / 函数', '学习档案 / 复习计划', '试卷导出 / 近30天'].map((item) => (
                    <div key={item} className="mb-2 rounded-md border border-border bg-card px-3 py-2 font-mono text-xs text-muted-foreground">
                      {item}
                    </div>
                  ))}
                </div>

                <div className="p-4">
                  <div className="space-y-3">
                    {timelineStages.map((stage, index) => (
                      <div key={stage.label} className="rounded-lg border border-border bg-background p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span
                            className="rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold"
                            style={{
                              backgroundColor: stage.color,
                              color: stage.label === '完成' ? '#ffffff' : 'var(--study-ink)',
                            }}
                          >
                            {stage.label}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">STEP {index + 1}</span>
                        </div>
                        <p className="mt-3 font-mono text-sm leading-6 text-foreground">{stage.text}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="border-t border-border bg-accent p-4 lg:border-l lg:border-t-0">
                  <div className="mb-3 font-mono text-xs text-muted-foreground">过程检查</div>
                  <div className="space-y-3 text-sm">
                    <div className="rounded-lg border border-border bg-card p-3">
                      <div className="text-xs text-muted-foreground">执行策略</div>
                      <div className="mt-1 font-medium">半自动，可暂停</div>
                    </div>
                    <div className="rounded-lg border border-border bg-card p-3">
                      <div className="text-xs text-muted-foreground">运行环境</div>
                      <div className="mt-1 flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-[var(--semantic-success)]" />
                        仅启用安全能力
                      </div>
                    </div>
                    <div className="rounded-lg border border-border bg-card p-3">
                      <div className="text-xs text-muted-foreground">输出物</div>
                      <div className="mt-1 flex items-center gap-2">
                        <Video className="h-4 w-4 text-muted-foreground" />
                        题单 / 讲义 / 视频
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </Card>
          </div>

          <aside className="space-y-4">
            <Card className="p-4">
              <div className="flex items-center justify-between">
                <h2 className="font-medium">运行中</h2>
                <span className="rounded-full bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
                  {runningTasks.length}
                </span>
              </div>
              <div className="mt-4 space-y-2">
                {runningTasks.length === 0 && (
                  <div className="rounded-lg border border-dashed border-border bg-accent px-3 py-8 text-center text-sm text-muted-foreground">
                    暂无运行中的任务
                  </div>
                )}
                {runningTasks.map((task) => (
                  <Link
                    key={task.id}
                    to={`/tasks?id=${encodeURIComponent(task.id)}`}
                    className="block rounded-lg border border-border bg-background p-3 transition-colors hover:bg-accent"
                  >
                    <div className="truncate text-sm font-medium">{task.title}</div>
                    <div className="mt-2 flex items-center justify-between gap-3 font-mono text-xs text-muted-foreground">
                      <span>{task.task_type}</span>
                      <span>{Math.round(Number(task.progress || 0))}%</span>
                    </div>
                  </Link>
                ))}
              </div>
            </Card>

            <Card className="p-4">
              <h2 className="font-medium">任务状态</h2>
              <div className="mt-4 space-y-2">
                {statusRows.length === 0 && <div className="text-sm text-muted-foreground">暂无状态数据</div>}
                {statusRows.map(([status, count]) => (
                  <div key={status} className="flex items-center justify-between gap-3 border-b border-border pb-2 last:border-b-0 last:pb-0">
                    <span className="font-mono text-xs text-muted-foreground">{status}</span>
                    <span className="font-mono text-sm text-foreground">{count}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card className="p-4">
              <h2 className="font-medium">常用学科</h2>
              <div className="mt-4 space-y-2">
                {(stats?.top_subjects || []).length === 0 && <div className="text-sm text-muted-foreground">暂无学科数据</div>}
                {(stats?.top_subjects || []).slice(0, 5).map((subject) => (
                  <div key={subject.subject} className="flex items-center justify-between gap-3 rounded-md bg-accent px-3 py-2">
                    <span className="text-sm">{subject.subject}</span>
                    <span className="font-mono text-xs text-muted-foreground">{subject.count}</span>
                  </div>
                ))}
              </div>
            </Card>
          </aside>
        </section>
      </div>
    </div>
  )
}
