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
  const res = await apiClient.get<{ templates?: UserTemplate[] }>('/templates', { params })
  return res.data.templates || []
}

export async function getTemplate(templateId: number): Promise<UserTemplate> {
  const res = await apiClient.get<{ template: UserTemplate }>(`/templates/${templateId}`)
  return res.data.template
}

export async function createTemplate(input: { type: string; name: string; body: Record<string, unknown> }): Promise<UserTemplate> {
  const res = await apiClient.post<{ template: UserTemplate }>('/templates', {
    template_type: input.type,
    name: input.name,
    body: input.body,
  })
  return res.data.template
}

export async function updateTemplate(
  templateId: number,
  input: { name?: string; type?: string; body?: Record<string, unknown> }
): Promise<UserTemplate> {
  const res = await apiClient.put<{ template: UserTemplate }>(`/templates/${templateId}`, {
    name: input.name,
    template_type: input.type,
    body: input.body,
  })
  return res.data.template
}

export async function deleteTemplate(templateId: number): Promise<void> {
  await apiClient.delete(`/templates/${templateId}`)
}

export async function exportTemplates(params?: { type?: string }): Promise<UserTemplate[]> {
  const res = await apiClient.get<{ templates?: UserTemplate[] }>('/templates/export', { params })
  return res.data.templates || []
}

export async function importTemplates(templates: UserTemplate[]): Promise<UserTemplate[]> {
  const res = await apiClient.post<{ created?: UserTemplate[] }>('/templates/import', { templates })
  return res.data.created || []
}

export const templatesApi = {
  listTemplates,
  getTemplate,
  createTemplate,
  updateTemplate,
  deleteTemplate,
  exportTemplates,
  importTemplates,
  list: async (): Promise<{ data: { templates: UserTemplate[] } }> => ({
    data: { templates: await listTemplates({ limit: 200 }) },
  }),
}
