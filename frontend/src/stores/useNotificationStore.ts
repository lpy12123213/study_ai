import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type TaskNotification = {
  id: string
  taskId: string
  title: string
  status: 'completed' | 'failed' | 'canceled' | string
  createdAt: string
  read: boolean
}

interface NotificationState {
  notifications: TaskNotification[]
  push: (n: Omit<TaskNotification, 'read'>) => void
  markAllRead: () => void
  markRead: (id: string) => void
  remove: (id: string) => void
  clear: () => void
}

const MAX_NOTIFICATIONS = 200

export const useNotificationStore = create<NotificationState>()(
  persist(
    (set) => ({
      notifications: [],
      push: (n) => {
        set((state) => {
          const id = String(n.id || `${n.taskId}-${n.status}-${Date.now()}`)
          const next: TaskNotification = { ...n, id, read: false }
          const deduped = state.notifications.filter((x) => x.id !== id)
          return { notifications: [next, ...deduped].slice(0, MAX_NOTIFICATIONS) }
        })
      },
      markAllRead: () => {
        set((state) => ({ notifications: state.notifications.map((n) => ({ ...n, read: true })) }))
      },
      markRead: (id) => {
        const key = String(id || '')
        if (!key) return
        set((state) => ({ notifications: state.notifications.map((n) => (n.id === key ? { ...n, read: true } : n)) }))
      },
      remove: (id) => {
        const key = String(id || '')
        if (!key) return
        set((state) => ({ notifications: state.notifications.filter((n) => n.id !== key) }))
      },
      clear: () => set({ notifications: [] }),
    }),
    { name: 'notifications' }
  )
)
