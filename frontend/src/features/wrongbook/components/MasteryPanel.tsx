import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { Loader2, Wand2 } from 'lucide-react'
// @ts-ignore recharts is installed by a separate worker for this feature branch.
import { PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { createPracticePaper } from '@/api/wrongbook'
import { useMastery } from '@/features/wrongbook/hooks/useMastery'

const ALL_SUBJECTS = '__all__'
const radarTooltipStyle = {
  background: 'rgba(5, 7, 10, 0.92)',
  border: '1px solid var(--border-default-color)',
  borderRadius: '12px',
  boxShadow: 'var(--shadow-elevation-high)',
  color: 'var(--text-primary)',
} as const

export function MasteryPanel() {
  const navigate = useNavigate()
  const [subject, setSubject] = useState(ALL_SUBJECTS)
  const selectedSubject = subject === ALL_SUBJECTS ? undefined : subject
  const masteryQuery = useMastery(selectedSubject)

  const practiceMutation = useMutation({
    mutationFn: (knowledgePoint: string) =>
      createPracticePaper({
        knowledge_point: knowledgePoint,
        paper_name: `薄弱点练习：${knowledgePoint}`,
      }),
    onSuccess: (res) => {
      const paperId = Number(res?.paper_id || 0)
      if (paperId > 0) navigate(`/papers/${paperId}`)
    },
  })

  const subjectOptions = useMemo(() => {
    const values = new Set<string>()
    if (selectedSubject) values.add(selectedSubject)
    for (const item of masteryQuery.data?.subjects || []) {
      if (item.subject) values.add(item.subject)
    }
    return Array.from(values)
  }, [masteryQuery.data?.subjects, selectedSubject])

  const points = masteryQuery.data?.knowledge_points || []
  const chartData = points.slice(0, 12).map((item) => ({
    name: item.knowledge_point || '未标注',
    avg_mastery: item.avg_mastery,
  }))
  const weakPoints = [...points].sort((a, b) => a.avg_mastery - b.avg_mastery).slice(0, 8)

  if (masteryQuery.isLoading) {
    return (
      <Card className="aurora-wrongbook-card p-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载掌握度...
        </div>
      </Card>
    )
  }

  if (masteryQuery.error) {
    return <ErrorNotice error={masteryQuery.error} />
  }

  return (
    <div className="space-y-4">
      <div className="aurora-wrongbook-toolbar flex max-w-xs items-center gap-2 p-3">
        <Select value={subject} onValueChange={setSubject}>
          <SelectTrigger className="bg-background/45">
            <SelectValue placeholder="选择学科" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_SUBJECTS}>全部学科</SelectItem>
            {subjectOptions.map((item) => (
              <SelectItem key={item} value={item}>
                {item}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {points.length === 0 ? (
        <Card className="aurora-wrongbook-card p-6">
          <div className="text-sm font-medium">暂无掌握度数据</div>
          <div className="mt-1 text-sm text-muted-foreground">为错题补充知识点后，这里会展示薄弱环节。</div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
          <Card className="aurora-wrongbook-card h-[360px] p-4">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={chartData}>
                <PolarGrid stroke="var(--border-subtle-color)" />
                <PolarAngleAxis dataKey="name" tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} />
                <Tooltip contentStyle={radarTooltipStyle} />
                <Radar
                  dataKey="avg_mastery"
                  name="平均掌握度"
                  stroke="var(--accent-brand-base)"
                  fill="var(--accent-ai-base)"
                  fillOpacity={0.28}
                />
              </RadarChart>
            </ResponsiveContainer>
          </Card>

          <Card className="aurora-wrongbook-card p-4">
            <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">薄弱知识点</div>
            <div className="mt-3 space-y-2">
              {weakPoints.map((item) => (
                <div key={`${item.subject}-${item.knowledge_point}`} className="aurora-wrongbook-item p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{item.knowledge_point || '未标注'}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        平均 {item.avg_mastery} · 最低 {item.min_mastery} · 到期 {item.due_count}/{item.count}
                      </div>
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => practiceMutation.mutate(item.knowledge_point || '')}
                      disabled={practiceMutation.isPending}
                    >
                      {practiceMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Wand2 className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
