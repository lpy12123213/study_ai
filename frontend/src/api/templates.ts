import { apiClient } from '@/api/client'

export type UserTemplate = {
  id: number
  template_type: string
  name: string
  body: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export async function listTemplates(params?: { type?: string; limit?: number }): Promise<UserTemplate[]> {
  const res = await apiClient.get('/templates', { params })
  return (res.data?.templates as UserTemplate[]) || []
}

export async function getTemplate(templateId: number): Promise<UserTemplate> {
  const res = await apiClient.get(`/templates/${templateId}`)
  return res.data?.template as UserTemplate
}

export async function createTemplate(input: { type: string; name: string; body: Record<string, unknown> }): Promise<UserTemplate> {
  const res = await apiClient.post('/templates', {
    template_type: input.type,
    name: input.name,
    body: input.body,
  })
  return res.data?.template as UserTemplate
}

export async function updateTemplate(
  templateId: number,
  input: { name?: string; type?: string; body?: Record<string, unknown> }
): Promise<UserTemplate> {
  const res = await apiClient.put(`/templates/${templateId}`, {
    name: input.name,
    template_type: input.type,
    body: input.body,
  })
  return res.data?.template as UserTemplate
}

export async function deleteTemplate(templateId: number): Promise<void> {
  await apiClient.delete(`/templates/${templateId}`)
}

export async function exportTemplates(params?: { type?: string }): Promise<UserTemplate[]> {
  const res = await apiClient.get('/templates/export', { params })
  return (res.data?.templates as UserTemplate[]) || []
}

export async function importTemplates(templates: UserTemplate[]): Promise<UserTemplate[]> {
  const res = await apiClient.post('/templates/import', { templates })
  return (res.data?.created as UserTemplate[]) || []
}

export const templatesApi = {
  listTemplates,
  getTemplate,
  createTemplate,
  updateTemplate,
  deleteTemplate,
  exportTemplates,
  importTemplates,
  list: async (): Promise<{ data: any }> => ({
    data: { templates: await listTemplates({ limit: 200 }) },
  }),
}
