import { apiClient } from '@/api/client'

export type KnowledgeVideoGenerateRequest = {
  topic: string
  subject?: string
  source_markdown?: string
  source_archive_id?: number
  duration_seconds?: number
  style?: string
  requirements?: string
  quality?: 'low' | 'medium' | 'high' | string
}

export type KnowledgeVideoTaskResult = {
  video_url?: string
  video_filename?: string
  subtitle_url?: string
  subtitle_filename?: string
  script_url?: string
  script_filename?: string
  metadata_url?: string
  metadata_filename?: string
  metadata?: {
    attempts?: number
    scene_name?: string
    duration_seconds?: number
    [key: string]: unknown
  }
}

type KnowledgeVideoGenerateResponse = {
  taskId?: string | number
}

export async function generateKnowledgeVideo(input: KnowledgeVideoGenerateRequest): Promise<{ taskId: string }> {
  const response = await apiClient.post<KnowledgeVideoGenerateResponse>('/tasks/knowledge-videos/generate', input)
  return { taskId: String(response.data?.taskId || '') }
}
