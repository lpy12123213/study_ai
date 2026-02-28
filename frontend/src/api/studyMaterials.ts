import { apiClient } from '@/api/client'

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
}

export async function getStudyMaterialsTask(taskId: string): Promise<StudyMaterialsTaskStatus> {
  const id = String(taskId || '').trim()
  if (!id) throw new Error('missing_task_id')
  const resp = await apiClient.get(`/study-materials/tasks/${encodeURIComponent(id)}`)
  return resp.data as StudyMaterialsTaskStatus
}

