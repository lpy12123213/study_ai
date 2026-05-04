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
  const res = await apiClient.get<{ annotations?: Annotation[] }>('/annotations', { params })
  return res.data.annotations || []
}

export async function createAnnotation(input: {
  item_type: string
  item_id: string
  anchor?: string
  snippet?: string
  content: string
  tags?: string[]
}): Promise<Annotation> {
  const res = await apiClient.post<{ annotation: Annotation }>('/annotations', input)
  return res.data.annotation
}

export async function exportAnnotations(): Promise<Annotation[]> {
  const res = await apiClient.get<{ annotations?: Annotation[] }>('/annotations/export')
  return res.data.annotations || []
}

export async function updateAnnotation(
  annotationId: number | string,
  patch: { content?: string; tags?: string[] },
): Promise<Annotation> {
  const res = await apiClient.patch<{ annotation: Annotation }>(`/annotations/${encodeURIComponent(String(annotationId))}`, patch)
  return res.data.annotation
}

export const annotationsApi = {
  listAnnotations,
  createAnnotation,
  exportAnnotations,
  updateAnnotation,
  list: async (): Promise<{ data: { annotations: Annotation[] } }> => ({
    data: { annotations: await listAnnotations() },
  }),
}
