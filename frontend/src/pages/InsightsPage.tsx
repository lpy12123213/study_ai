import { useMemo, useState } from 'react'
import { Activity, BookOpenCheck, CalendarRange, Download, Gauge, Loader2, TrendingUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { downloadInsightsCsv, type InsightsParams } from '@/api/insights'
import { formatPercent } from '@/features/insights/components/format'
import {
  AccuracyByTypePanel,
  ActivityPanel,
  EssayPanel,
  ExamTrendPanel,
  useInsights,
  WrongbookMasteryPanel,
} from '@/features/insights'

export default function InsightsPage() {
  const [days, setDays] = useState(30)
  const [subject, setSubject] = useState('')
  const [exporting, setExporting] = useState(false)

  const params: InsightsParams = useMemo(
    () => ({
      days,
      ...(subject.trim() ? { subject: subject.trim() } : {}),
    }),
    [days, subject]
  )

  const { data, isLoading, error } = useInsights(params)
  const heroStats = [
    {
      label: '考试均分',
      value: formatPercent(data?.exams?.avg_score_ratio),
      detail: `${data?.exams?.recent?.length ?? 0} 次近期交卷`,
      icon: Gauge,
    },
    {
      label: '连续学习',
      value: `${data?.activity?.current_streak ?? 0} 天`,
      detail: `${data?.activity?.active_days ?? 0} 个活跃日`,
      icon: Activity,
    },
    {
      label: '错题规模',
      value: `${data?.wrongbook?.total ?? 0}`,
      detail: `${data?.wrongbook?.weak_points?.length ?? 0} 个薄弱点`,
      icon: BookOpenCheck,
    },
  ]

  const downloadCsv = async () => {
    setExporting(true)
    try {
      const { blob, filename } = await downloadInsightsCsv(params)
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = filename || `insights-${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="aurora-insights-screen min-h-full px-4 py-6 md:px-6 lg:px-8">
      <div className="mx-auto max-w-[1440px] space-y-6">
        <section className="aurora-insights-hero p-5 md:p-8">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_390px] xl:items-end">
            <div>
              <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                <TrendingUp className="h-3.5 w-3.5 text-[var(--accent-brand-base)]" />
                Learning analytics
              </div>
              <div className="max-w-3xl">
                <h1 className="app-display text-4xl text-foreground md:text-6xl">学情分析观测舱</h1>
                <p className="mt-4 max-w-2xl text-base leading-7 text-muted-foreground">
                  把考试、错题、作文与学习计划汇入同一块仪表盘，优先暴露趋势、薄弱点和下一步复习信号。
                </p>
              </div>
              <div className="mt-6 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                <span className="inline-flex items-center gap-2 rounded-full border border-border bg-background/35 px-3 py-1">
                  <CalendarRange className="h-4 w-4 text-[var(--accent-brand-base)]" />
                  {data?.from || '--'} → {data?.to || '--'}
                </span>
                {isLoading && (
                  <span className="inline-flex items-center gap-2 rounded-full border border-border bg-background/35 px-3 py-1">
                    <Loader2 className="h-4 w-4 animate-spin text-[var(--accent-ai-base)]" />
                    正在同步数据
                  </span>
                )}
              </div>
            </div>

            <div className="aurora-insights-control-panel space-y-4 p-4">
              <div className="grid grid-cols-3 gap-2">
                {[7, 30, 90].map((d) => (
                  <Button
                    key={d}
                    type="button"
                    size="sm"
                    variant="outline"
                    className={days === d ? 'aurora-insights-tab-active' : 'aurora-insights-tab'}
                    onClick={() => setDays(d)}
                  >
                    近{d}天
                  </Button>
                ))}
              </div>
              <Input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                placeholder="按学科过滤"
                className="h-10 border-border bg-background/45"
              />
              <Button type="button" className="w-full" variant="outline" onClick={downloadCsv} disabled={exporting}>
                {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                导出 CSV
              </Button>
            </div>
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-3">
            {heroStats.map((stat) => {
              const Icon = stat.icon
              return (
                <div key={stat.label} className="aurora-insights-kpi">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs font-medium text-muted-foreground">{stat.label}</span>
                    <Icon className="h-4 w-4 text-[var(--accent-brand-base)]" />
                  </div>
                  <div className="mt-3 font-mono text-3xl text-foreground">{stat.value}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{stat.detail}</div>
                </div>
              )
            })}
          </div>
        </section>

        {Boolean(error) && <ErrorNotice error={error} />}

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
          <div className="space-y-6">
            <ExamTrendPanel data={data?.exams} />
            <AccuracyByTypePanel data={data?.exams?.accuracy_by_type} />
          </div>
          <div className="space-y-6">
            <ActivityPanel data={data?.activity} />
            <WrongbookMasteryPanel data={data?.wrongbook} />
            <EssayPanel data={data?.essays} />
          </div>
        </section>
      </div>
    </div>
  )
}
