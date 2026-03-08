import { create } from 'zustand'

export type RequestLogItem = {
  requestId: string
  url?: string
  status?: number
  createdAt: number
}

interface RequestLogState {
  items: RequestLogItem[]
  push: (item: Omit<RequestLogItem, 'createdAt'> & { createdAt?: number }) => void
  clear: () => void
}

const MAX_ITEMS = 30

export const useRequestLogStore = create<RequestLogState>()((set) => ({
  items: [],
  push: (item) => {
    const rid = String(item.requestId || '').trim()
    if (!rid) return
    set((state) => {
      const next: RequestLogItem = {
        requestId: rid,
        url: item.url ? String(item.url) : undefined,
        status: typeof item.status === 'number' ? item.status : undefined,
        createdAt: item.createdAt ?? Date.now(),
      }
      const deduped = state.items.filter((x) => x.requestId !== rid)
      return { items: [next, ...deduped].slice(0, MAX_ITEMS) }
    })
  },
  clear: () => set({ items: [] }),
}))

