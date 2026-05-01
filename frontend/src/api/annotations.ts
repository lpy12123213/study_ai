import { apiClient } from '@/api/client'

export type Annotation = {
  id: number
  item_type: string
  item_id: string
  anchor: string
  snippet: string
  content: string
  tags: string[]
  created_at?: string
  updated_at?: string
}

export async function listAnnotations(params?: {
  item_type?: string
  item_id?: string
  tag?: string
  limit?: number
}): Promise<Annotation[]> {
  const res = await apiClient.get('/annotations', { params })
  return (res.data?.annotations as Annotation[]) || []
}

export async function createAnnotation(input: {
  item_type: string
  item_id: string
  anchor?: string
  snippet?: string
  content: string
  tags?: string[]
}): Promise<Annotation> {
  const res = await apiClient.post('/annotations', input)
  return res.data?.annotation as Annotation
}

export async function exportAnnotations(): Promise<Annotation[]> {
  const res = await apiClient.get('/annotations/export')
  return (res.data?.annotations as Annotation[]) || []
}

export async function updateAnnotation(
  annotationId: number | string,
  patch: { content?: string; tags?: string[] },
): Promise<Annotation> {
  const res = await apiClient.patch(`/annotations/${encodeURIComponent(String(annotationId))}`, patch)
  return res.data?.annotation as Annotation
}

export const annotationsApi = {
  listAnnotations,
  createAnnotation,
  exportAnnotations,
  updateAnnotation,
  list: async (): Promise<{ data: any }> => ({
    data: { annotations: await listAnnotations() },
  }),
}
