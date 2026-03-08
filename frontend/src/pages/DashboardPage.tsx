import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, Download, Loader2, TrendingUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { downloadObjectUrl } from '@/api/client'
import * as dashboardApi from '@/api/dashboard'

function pct(value: number): string {
  if (!Number.isFinite(value)) return '--'
  return `${Math.round(value * 100)}%`
}

function sec(value: number): string {
  if (!Number.isFinite(value)) return '--'
  if (value < 60) return `${Math.round(value)}s`
  const m = Math.round(value / 60)
  return `${m}min`
}

export default function DashboardPage() {
  const [days, setDays] = useState(30)

  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard', days],
    queryFn: () => dashboardApi.getDashboardStats({ days }),
    refetchInterval: 15_000,
  })

  const stats = data

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
    <div className="h-full flex flex-col overflow-hidden bg-background">
      <div className="border-b border-border p-4 flex items-center justify-between sticky top-0 bg-background/80 backdrop-blur-sm z-10">
        <div className="flex items-center gap-2 font-semibold">
          <BarChart3 className="h-4 w-4 text-primary" />
          学习数据面板
        </div>
        <div className="flex items-center gap-2">
          {[7, 30, 90].map((d) => (
            <Button key={d} type="button" size="sm" variant={days === d ? 'default' : 'outline'} onClick={() => setDays(d)}>
              近{d}天
            </Button>
          ))}
          <Button type="button" size="sm" variant="outline" onClick={downloadCsv} disabled={!stats}>
            <Download className="h-4 w-4 mr-2" />
            导出 CSV
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto p-6">
        <div className="max-w-5xl mx-auto space-y-4">
          {Boolean(error) && <ErrorNotice error={error} />}
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          )}

          {stats && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <Card className="p-4">
                  <div className="text-xs text-muted-foreground">任务总数</div>
                  <div className="text-2xl font-semibold mt-1">{stats.tasks_total}</div>
                </Card>
                <Card className="p-4">
                  <div className="text-xs text-muted-foreground">完成率</div>
                  <div className="text-2xl font-semibold mt-1">{pct(stats.completion_rate)}</div>
                </Card>
                <Card className="p-4">
                  <div className="text-xs text-muted-foreground">平均耗时</div>
                  <div className="text-2xl font-semibold mt-1">{sec(stats.avg_duration_s)}</div>
                </Card>
                <Card className="p-4">
                  <div className="text-xs text-muted-foreground">导出文件</div>
                  <div className="text-2xl font-semibold mt-1">{stats.exports_total}</div>
                </Card>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <Card className="p-4">
                  <div className="font-medium flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-primary" />
                    常用学科
                  </div>
                  <div className="mt-3 space-y-2">
                    {(stats.top_subjects || []).length === 0 && (
                      <div className="text-sm text-muted-foreground">暂无数据</div>
                    )}
                    {(stats.top_subjects || []).map((s) => (
                      <div key={s.subject} className="flex items-center justify-between gap-3">
                        <div className="text-sm">{s.subject}</div>
                        <div className="text-xs text-muted-foreground">{s.count}</div>
                      </div>
                    ))}
                  </div>
                </Card>

                <Card className="p-4">
                  <div className="font-medium">任务类型</div>
                  <div className="mt-3 space-y-2">
                    {Object.entries(stats.tasks_by_type || {})
                      .sort((a, b) => (b[1] || 0) - (a[1] || 0))
                      .map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between gap-3">
                          <div className="text-sm font-mono">{k}</div>
                          <div className="text-xs text-muted-foreground">{v}</div>
                        </div>
                      ))}
                  </div>
                </Card>
              </div>

              <Card className="p-4">
                <div className="font-medium">时间范围</div>
                <div className="mt-2 text-xs text-muted-foreground">
                  {stats.from} → {stats.to}
                </div>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
