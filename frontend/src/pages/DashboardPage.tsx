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
  TrendingUp,
  Video,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { timelineStages } from '@/features/dashboard/utils'
import { useDashboard } from '@/features/dashboard/hooks/useDashboard'

const SUMMARY_ICONS = [BarChart3, CheckCircle2, TimerReset, FileText] as const
const FEATURE_ICONS = [Sparkles, BookOpen, Library] as const

export default function DashboardPage() {
  const {
    days,
    setDays,
    stats,
    isLoading,
    error,
    reviewDueCount,
    runningTasks,
    statusRows,
    insightRows,
    featureCards,
    summaryCards,
    downloadCsv,
  } = useDashboard()

  return (
    <div className="aurora-dashboard-screen min-h-full px-4 py-6 md:px-6 lg:px-8">
      <div className="mx-auto max-w-[1440px] space-y-6">
        <section className="aurora-dashboard-hero grid gap-6 p-5 md:p-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div className="max-w-3xl">
            <div className="mb-4 inline-flex rounded-full border border-border bg-card/70 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              学习工作台
            </div>
            <h1 className="app-display text-4xl text-foreground md:text-6xl">AI 学习任务指挥舱</h1>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground md:text-base">
              从检索、生成、审查到导出，所有长任务都沿着可复查的时间线推进。界面保留足够留白，
              也保留关键中间产物。
            </p>
          </div>

          <div className="aurora-dashboard-launcher flex flex-wrap items-center gap-2 p-3">
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

        <div className="aurora-dashboard-filter flex flex-wrap items-center justify-between gap-3 px-4 py-3">
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
                className={days === d ? 'aurora-dashboard-tab-active' : 'aurora-dashboard-tab'}
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
          {summaryCards.map(({ label, value, hint }, index) => {
            const Icon = SUMMARY_ICONS[index] ?? BarChart3
            return (
            <Card key={label} className="aurora-dashboard-stat p-4">
              <div className="flex items-center justify-between gap-3 text-muted-foreground">
                <span className="text-xs">{label}</span>
                <Icon className="h-4 w-4 text-[var(--accent-brand-base)]" />
              </div>
              <div className="mt-3 font-mono text-3xl text-foreground">{value}</div>
              <div className="mt-2 text-xs text-muted-foreground">{hint}</div>
            </Card>
            )
          })}
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-6">
            <div className="grid gap-4 md:grid-cols-3">
              {featureCards.map(({ title, description, path, meta, stage, color }, index) => {
                const Icon = FEATURE_ICONS[index] ?? Sparkles
                return (
                <Link key={path} to={path} className="aurora-dashboard-feature group block p-5">
                  <div className="flex items-start justify-between gap-4">
                    <span className="flex h-10 w-10 items-center justify-center rounded-md border border-border bg-accent/60">
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
                )
              })}
            </div>

            <Card className="aurora-dashboard-workflow overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
                <div>
                  <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">任务时间线</div>
                  <h2 className="mt-1 text-xl font-medium">可复查的 AI 工作流</h2>
                </div>
                <Button asChild variant="outline" size="sm">
                  <Link to="/deepthink">打开深度解题</Link>
                </Button>
              </div>

              <div className="grid min-h-[420px] lg:grid-cols-[220px_minmax(0,1fr)_260px]">
                <div className="aurora-dashboard-pane border-b border-border p-4 lg:border-b-0 lg:border-r">
                  <div className="mb-3 flex items-center justify-between gap-2 font-mono text-xs text-muted-foreground">
                    <span>学情速览</span>
                    <TrendingUp className="h-4 w-4 text-[var(--accent-brand-base)]" />
                  </div>
                  <Link to="/insights" className="aurora-dashboard-link group block px-3 py-3">
                    <div className="space-y-2">
                      {insightRows.map((item) => (
                        <div key={item.label} className="flex items-start justify-between gap-3">
                          <span className="text-xs text-muted-foreground">{item.label}</span>
                          <span className="max-w-[130px] truncate text-right font-mono text-xs text-foreground">{item.value}</span>
                        </div>
                      ))}
                    </div>
                    <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
                      <span>打开学情分析</span>
                      <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                    </div>
                  </Link>
                </div>

                <div className="p-4">
                  <div className="space-y-3">
                    {timelineStages.map((stage, index) => (
                      <div key={stage.label} className="aurora-dashboard-stage p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span
                            className="rounded-full px-2.5 py-1 font-mono text-[11px] font-semibold"
                            style={{
                              backgroundColor: stage.color,
                              color: stage.label === '完成' ? 'var(--text-display)' : 'var(--study-ink)',
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

                <div className="aurora-dashboard-pane border-t border-border p-4 lg:border-l lg:border-t-0">
                  <div className="mb-3 font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">过程检查</div>
                  <div className="space-y-3 text-sm">
                    <div className="aurora-dashboard-probe p-3">
                      <div className="text-xs text-muted-foreground">执行策略</div>
                      <div className="mt-1 font-medium">半自动，可暂停</div>
                    </div>
                    <div className="aurora-dashboard-probe p-3">
                      <div className="text-xs text-muted-foreground">运行环境</div>
                      <div className="mt-1 flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-[var(--semantic-success)]" />
                        仅启用安全能力
                      </div>
                    </div>
                    <div className="aurora-dashboard-probe p-3">
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
            <Card className="aurora-dashboard-card p-4">
              <Link to="/wrongbook?tab=review" className="group block">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium">今日待复习</div>
                    <div className="mt-2 font-mono text-3xl text-foreground">{reviewDueCount}</div>
                  </div>
                  <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
                </div>
                <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
                  <span>打开错题复习</span>
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </div>
              </Link>
            </Card>

            <Card className="aurora-dashboard-card p-4">
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
                    className="aurora-dashboard-link block p-3"
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

            <Card className="aurora-dashboard-card p-4">
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

            <Card className="aurora-dashboard-card p-4">
              <h2 className="font-medium">常用学科</h2>
              <div className="mt-4 space-y-2">
                {(stats?.top_subjects || []).length === 0 && <div className="text-sm text-muted-foreground">暂无学科数据</div>}
                {(stats?.top_subjects || []).slice(0, 5).map((subject) => (
                  <div key={subject.subject} className="aurora-dashboard-probe flex items-center justify-between gap-3 px-3 py-2">
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
