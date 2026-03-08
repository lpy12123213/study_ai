import { apiClient, downloadBlob } from '@/api/client'

export type DashboardStats = {
  from: string
  to: string
  tasks_total: number
  tasks_by_type: Record<string, number>
  tasks_by_status: Record<string, number>
  completion_rate: number
  avg_duration_s: number
  exports_total: number
  exports_by_type: Record<string, number>
  top_subjects: Array<{ subject: string; count: number }>
}

export async function getDashboardStats(params?: { days?: number; from?: string; to?: string }): Promise<DashboardStats> {
  const res = await apiClient.get('/dashboard/stats', { params })
  return res.data as DashboardStats
}

export async function downloadDashboardCsv(params?: { days?: number; from?: string; to?: string }): Promise<{ filename?: string }> {
  const qs = new URLSearchParams()
  if (params?.days != null) qs.set('days', String(params.days))
  if (params?.from) qs.set('from', params.from)
  if (params?.to) qs.set('to', params.to)
  const q = qs.toString()
  const url = `/dashboard/export${q ? `?${q}` : ''}`
  const { filename } = await downloadBlob(url, { headers: {}, signal: undefined })
  return { filename }
}
