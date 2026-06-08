import { apiClient } from '@/api/client'

export type ShareLinkMeta = {
  token: string
  item_type: string
  expires_at?: string
  created_at?: string
  has_password: boolean
}

export type SharedContent = {
  item_type: string
  paper?: Record<string, unknown>
  study_archive?: Record<string, unknown>
  template?: Record<string, unknown>
}

export async function createShareLink(input: {
  itemType: string
  itemId: string | number
  expiresInS?: number | null
  password?: string
}): Promise<ShareLinkMeta> {
  const res = await apiClient.post('/share-links', {
    item_type: input.itemType,
    item_id: String(input.itemId),
    expires_in_s: input.expiresInS,
    password: input.password || '',
  })
  return res.data as ShareLinkMeta
}

export async function getShareMeta(token: string): Promise<ShareLinkMeta> {
  const res = await apiClient.get(`/share/${encodeURIComponent(token)}`)
  return res.data as ShareLinkMeta
}

export async function validateShareLink(token: string, password: string): Promise<ShareLinkMeta> {
  const res = await apiClient.post(`/share/${encodeURIComponent(token)}/validate`, { password })
  return res.data as ShareLinkMeta
}

export async function fetchSharedContent(
  token: string,
  password: string
): Promise<SharedContent> {
  const res = await apiClient.post<SharedContent>(`/share/${encodeURIComponent(token)}/content`, { password })
  return res.data
}
