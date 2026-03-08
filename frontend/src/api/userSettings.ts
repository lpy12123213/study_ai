import { apiClient } from '@/api/client'

export type UserSettings = {
  user_id?: string
  settings: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export async function getUserSettings(): Promise<UserSettings> {
  const res = await apiClient.get('/user-settings')
  return res.data as UserSettings
}

export async function putUserSettings(settings: Record<string, unknown>): Promise<UserSettings> {
  const res = await apiClient.put('/user-settings', { settings })
  return res.data as UserSettings
}

export async function exportUserSettings(): Promise<UserSettings> {
  const res = await apiClient.get('/user-settings/export')
  return res.data as UserSettings
}

export async function importUserSettings(settings: Record<string, unknown>): Promise<UserSettings> {
  const res = await apiClient.post('/user-settings/import', { settings })
  return res.data as UserSettings
}

