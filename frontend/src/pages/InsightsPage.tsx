import { useMemo, useState } from 'react'
import { Download, Loader2, TrendingUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { downloadInsightsCsv, type InsightsParams } from '@/api/insights'
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
    <div className="min-h-full bg-background px-4 py-8 md:px-6 lg:px-8">
      <div className="mx-auto max-w-[1280px] space-y-6">
        <section className="grid gap-4 border-b border-border pb-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div>
            <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 font-mono text-[11px] font-semibold text-muted-foreground">
              <TrendingUp className="h-3.5 w-3.5" />
              Learning analytics
            </div>
            <h1 className="app-display text-3xl text-foreground md:text-4xl">学情分析</h1>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              <span>数据窗口：{data?.from || '--'} → {data?.to || '--'}</span>
            </div>
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
            <Input
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              placeholder="学科"
              className="h-9 w-24"
            />
            <Button type="button" size="sm" variant="outline" onClick={downloadCsv} disabled={exporting}>
              {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              导出 CSV
            </Button>
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
