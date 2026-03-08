import { create } from 'zustand'

export type ToastItem = {
  id: string
  title: string
  taskId?: string
  status?: string
  createdAt: number
}

interface ToastState {
  toasts: ToastItem[]
  pushToast: (t: Omit<ToastItem, 'createdAt'> & { createdAt?: number }) => void
  removeToast: (id: string) => void
  clearToasts: () => void
}

const MAX_TOASTS = 5

export const useToastStore = create<ToastState>()((set) => ({
  toasts: [],
  pushToast: (t) => {
    set((state) => {
      const id = String(t.id || `toast-${Date.now()}`)
      const next: ToastItem = { ...t, id, createdAt: t.createdAt ?? Date.now() }
      const deduped = state.toasts.filter((x) => x.id !== id)
      return { toasts: [next, ...deduped].slice(0, MAX_TOASTS) }
    })
  },
  removeToast: (id) => {
    const key = String(id || '')
    if (!key) return
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== key) }))
  },
  clearToasts: () => set({ toasts: [] }),
}))

