import { apiClient } from '@/api/client'

export type StudyMaterialsStage = '' | 'search' | 'aggregate' | 'write' | 'export'

export interface StudyMaterialsPerKpState {
  search_done?: boolean
  aggregate_done?: boolean
  write_done?: boolean
  export_done?: boolean
  web_results_count?: number
}

export interface StudyMaterialsSearchResultSummary {
  title: string
  url: string
  snippet?: string | null
}

export interface StudyMaterialsSearchSummary {
  provider?: string
  source_query?: string
  results?: StudyMaterialsSearchResultSummary[]
}

export interface StudyMaterialsTaskStatus {
  task_id: string
  query: string
  user_id: string
  status: 'running' | 'completed' | 'failed'
  error?: string | null
  created_at_s: number
  updated_at_s: number
  first_seq: number
  last_seq: number
  last_success_step?: string | null
  last_failed_step?: string | null
  last_success_stage?: StudyMaterialsStage | null
  last_failed_stage?: StudyMaterialsStage | null
  per_kp_state?: Record<string, StudyMaterialsPerKpState> | null
  search_summary_by_kp?: Record<string, StudyMaterialsSearchSummary> | null
}

export async function getStudyMaterialsTask(taskId: string): Promise<StudyMaterialsTaskStatus> {
  const id = String(taskId || '').trim()
  if (!id) throw new Error('missing_task_id')
  const resp = await apiClient.get(`/study-materials/tasks/${encodeURIComponent(id)}`)
  return resp.data as StudyMaterialsTaskStatus
}
