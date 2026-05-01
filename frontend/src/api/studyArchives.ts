import { apiClient } from '@/api/client'

export type StudyArchive = {
  id: number
  subject: string
  topic: string
  base_fingerprint?: string
  preset?: string
  requirements?: string
  markdown: string
  sections?: Array<Record<string, any>>
  created_at?: string
  updated_at?: string
}

export async function getStudyArchive(archiveId: string): Promise<StudyArchive> {
  const response = await apiClient.get(`/study-archives/${encodeURIComponent(String(archiveId))}`)
  return response.data as any
}

export async function listStudyArchives(params?: { limit?: number; offset?: number }): Promise<StudyArchive[]> {
  const res = await apiClient.get('/study-archives', { params })
  return (res.data?.items as StudyArchive[]) || []
}

export async function createStudyArchive(input: {
  subject: string
  topic: string
  preset?: string
  requirements?: string
  markdown: string
  sections?: Array<Record<string, any>>
}): Promise<StudyArchive> {
  const res = await apiClient.post('/study-archives', {
    subject: input.subject,
    topic: input.topic,
    preset: input.preset || '',
    requirements: input.requirements || '',
    markdown: input.markdown,
    sections: input.sections || [],
  })
  return (res.data?.archive as StudyArchive) || (res.data as StudyArchive)
}

export async function cloneStudyArchive(
  archiveId: number | string,
  input?: { topic?: string; preset?: string; requirements?: string }
): Promise<StudyArchive> {
  const res = await apiClient.post(`/study-archives/${encodeURIComponent(String(archiveId))}/clone`, input || {})
  return (res.data?.archive as StudyArchive) || (res.data as StudyArchive)
}

export const studyArchivesApi = {
  getStudyArchive,
  listStudyArchives,
  createStudyArchive,
  cloneStudyArchive,
  get: async (archiveId: string): Promise<{ data: any }> => ({
    data: await getStudyArchive(archiveId),
  }),
}
