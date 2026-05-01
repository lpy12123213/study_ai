import { apiClient } from '@/api/client'

export type GeneratedFile = {
  filename: string
  file_type: string
  mime_type: string
  bytes: number
  created_at?: string
  expires_at?: string
  url?: string
}

export async function listGeneratedFiles(params?: { type?: string; limit?: number; offset?: number }): Promise<GeneratedFile[]> {
  const res = await apiClient.get('/exports/files', { params })
  return (res.data?.files as GeneratedFile[]) || []
}

export async function zipGeneratedFiles(filenames: string[]): Promise<{ url: string; filename: string }> {
  const res = await apiClient.post('/exports/zip', { filenames })
  return res.data as { url: string; filename: string }
}

export const exportsApi = {
  listGeneratedFiles,
  zipGeneratedFiles,
  list: async (): Promise<{ data: any }> => ({
    data: { exports: await listGeneratedFiles({ limit: 200, offset: 0 }) },
  }),
}
