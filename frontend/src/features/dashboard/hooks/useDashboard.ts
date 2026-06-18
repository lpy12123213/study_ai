import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { downloadObjectUrl } from '@/api/client'
import * as dashboardApi from '@/api/dashboard'
import * as insightsApi from '@/api/insights'
import * as wrongbookApi from '@/api/wrongbook'
import { DASHBOARD_REFETCH_INTERVAL_MS, useRunningTasks } from '@/hooks/useRunningTasks'
import {
  isAiGenerateTask,
  isQuestionLibraryTask,
  isStudyMaterialTask,
  pct,
  sec,
  sumTaskTypes,
} from '../utils'

export type DashboardState = {
  days: number
  setDays: (value: number) => void
  stats: Awaited<ReturnType<typeof dashboardApi.getDashboardStats>> | undefined
  isLoading: boolean
  error: unknown
  insights: Awaited<ReturnType<typeof insightsApi.getInsightsOverview>> | undefined
  reviewDueCount: number
  runningTasks: Array<{ id: string; title: string; task_type: string; progress?: number }>
  statusRows: Array<[string, number]>
  insightRows: Array<{ label: string; value: string }>
  featureCards: Array<{
    title: string
    description: string
    path: string
    meta: string
    stage: string
    color: string
  }>
  summaryCards: Array<{ label: string; value: string | number; hint: string }>
  downloadCsv: () => Promise<void>
}

export function useDashboard(): DashboardState {
  const [days, setDays] = useState(30)

  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['dashboard', days],
    queryFn: () => dashboardApi.getDashboardStats({ days }),
    refetchInterval: DASHBOARD_REFETCH_INTERVAL_MS,
  })

  const { data: insights } = useQuery({
    queryKey: ['insights', 'dashboard-preview', days],
    queryFn: () => insightsApi.getInsightsOverview({ days }),
    refetchInterval: DASHBOARD_REFETCH_INTERVAL_MS,
  })

  const { data: reviewQueue } = useQuery({
    queryKey: ['wrongbook', 'dashboard-review-queue'],
    queryFn: () => wrongbookApi.getReviewQueue({ limit: 1 }),
    refetchInterval: DASHBOARD_REFETCH_INTERVAL_MS,
  })

  const { data: runningTasksData } = useRunningTasks()

  const runningTasks = (runningTasksData?.tasks ?? []).slice(0, 5)
  const typeCounts = stats?.tasks_by_type
  const statusRows = Object.entries(stats?.tasks_by_status ?? {})
    .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
    .slice(0, 5)
  const latestExam = insights?.exams?.recent?.[0]
  const weakPoint = insights?.wrongbook?.weak_points?.[0]
  const plan = insights?.activity?.plan_completion
  const reviewDueCount = Number(reviewQueue?.due_count || 0)
  const insightRows = [
    { label: '最新成绩', value: latestExam ? pct(latestExam.score_ratio) : '--' },
    { label: '薄弱点', value: weakPoint ? `${weakPoint.knowledge_point} ${pct(weakPoint.avg_mastery)}` : '--' },
    { label: '活跃', value: insights?.activity ? `${insights.activity.active_days}天 / 连续${insights.activity.current_streak}天` : '--' },
    { label: '计划', value: plan && plan.total > 0 ? `${plan.completed}/${plan.total}` : '--' },
  ]

  const featureCards = [
    {
      title: 'AI 出题',
      description: '从知识点、题库和蓝图生成可审查题目，保留推理与草稿痕迹。',
      path: '/ai-generate',
      meta: `${sumTaskTypes(typeCounts, [isAiGenerateTask]) || '--'} 次任务`,
      stage: '生成',
      color: 'var(--timeline-edit)',
    },
    {
      title: '自学资料',
      description: '把章节、错题和外部资料整理成结构化讲义与复习路径。',
      path: '/study-materials',
      meta: `${sumTaskTypes(typeCounts, [isStudyMaterialTask]) || '--'} 次任务`,
      stage: '阅读',
      color: 'var(--timeline-read)',
    },
    {
      title: '本地题库',
      description: '集中管理题目、标签、来源与过滤条件，支撑后续生成流程。',
      path: '/question-library',
      meta: `${sumTaskTypes(typeCounts, [isQuestionLibraryTask]) || '--'} 条线索`,
      stage: '检索',
      color: 'var(--timeline-grep)',
    },
  ]

  const summaryCards = [
    { label: '任务总数', value: stats?.tasks_total ?? '--', hint: `近 ${days} 天` },
    { label: '完成率', value: pct(stats?.completion_rate), hint: '按任务状态统计' },
    { label: '平均耗时', value: sec(stats?.avg_duration_s), hint: '完成任务均值' },
    { label: '导出文件', value: stats?.exports_total ?? '--', hint: '试卷与资料归档' },
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

  return {
    days,
    setDays,
    stats,
    isLoading,
    error,
    insights,
    reviewDueCount,
    runningTasks,
    statusRows,
    insightRows,
    featureCards,
    summaryCards,
    downloadCsv,
  }
}
