import { apiClient } from '@/api/client'

export type ItemMeta = {
  user_id: string
  item_type: string
  item_id: string
  starred: boolean
  pinned: boolean
  tags: string[]
  updated_at?: string
}

export async function listMeta(params: {
  itemType?: string
  starred?: boolean
  pinned?: boolean
  tag?: string
  limit?: number
}): Promise<{ items: ItemMeta[]; count: number }> {
  const response = await apiClient.get('/meta', {
    params: {
      item_type: params.itemType,
      starred: params.starred,
      pinned: params.pinned,
      tag: params.tag,
      limit: params.limit ?? 500,
    },
  })
  return response.data as { items: ItemMeta[]; count: number }
}

export async function getMeta(itemType: string, itemId: string): Promise<ItemMeta> {
  const response = await apiClient.get<ItemMeta>(`/meta/${encodeURIComponent(itemType)}/${encodeURIComponent(itemId)}`)
  return response.data
}

export async function setMeta(
  itemType: string,
  itemId: string,
  patch: { starred?: boolean; pinned?: boolean; tags?: string[] },
): Promise<ItemMeta> {
  const response = await apiClient.post<ItemMeta>(`/meta/${encodeURIComponent(itemType)}/${encodeURIComponent(itemId)}`, patch)
  return response.data
}

