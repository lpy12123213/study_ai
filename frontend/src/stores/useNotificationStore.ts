import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ToastItem = {
  id: string
  title: string
  taskId?: string
  traceId?: string
  status?: string
  createdAt: number
}

type ToastInput = Omit<ToastItem, 'id' | 'createdAt'> & {
  id?: string
  createdAt?: number
}

export type TaskNotification = {
  id: string
  taskId: string
  title: string
  traceId?: string
  status: 'completed' | 'failed' | 'canceled' | string
  createdAt: string
  read: boolean
}

interface NotificationState {
  notifications: TaskNotification[]
  toasts: ToastItem[]

  addNotification: (n: Omit<TaskNotification, 'read'>) => void
  addToast: (t: ToastInput) => void
  dismiss: (id: string) => void

  // Notification-specific helpers.
  markAllRead: () => void
  markRead: (id: string) => void
  removeNotification: (id: string) => void
  clearNotifications: () => void

  // Toast-specific helpers.
  removeToast: (id: string) => void
  clearToasts: () => void

  // Back-compat aliases.
  push: (n: Omit<TaskNotification, 'read'>) => void
  remove: (id: string) => void
  clear: () => void
  pushToast: (t: ToastInput) => void
}

const MAX_NOTIFICATIONS = 200
const MAX_TOASTS = 5
let toastSequence = 0

function nextToastId(): string {
  toastSequence = (toastSequence + 1) % Number.MAX_SAFE_INTEGER
  return `toast-${Date.now()}-${toastSequence}`
}

export const useNotificationStore = create<NotificationState>()(
  persist(
    (set, get) => ({
      notifications: [],
      toasts: [],

      addNotification: (n) => {
        set((state) => {
          const id = String(n.id || `${n.taskId}-${n.status}-${Date.now()}`)
          const next: TaskNotification = { ...n, id, read: false }
          const deduped = state.notifications.filter((x) => x.id !== id)
          return { notifications: [next, ...deduped].slice(0, MAX_NOTIFICATIONS) }
        })
      },
      addToast: (t) => {
        set((state) => {
          const id = String(t.id || nextToastId())
          const next: ToastItem = { ...t, id, createdAt: t.createdAt ?? Date.now() }
          const deduped = state.toasts.filter((x) => x.id !== id)
          return { toasts: [next, ...deduped].slice(0, MAX_TOASTS) }
        })
      },
      dismiss: (id) => {
        const key = String(id || '')
        if (!key) return
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== key),
          toasts: state.toasts.filter((t) => t.id !== key),
        }))
      },

      markAllRead: () => {
        set((state) => ({ notifications: state.notifications.map((n) => ({ ...n, read: true })) }))
      },
      markRead: (id) => {
        const key = String(id || '')
        if (!key) return
        set((state) => ({ notifications: state.notifications.map((n) => (n.id === key ? { ...n, read: true } : n)) }))
      },
      removeNotification: (id) => {
        const key = String(id || '')
        if (!key) return
        set((state) => ({ notifications: state.notifications.filter((n) => n.id !== key) }))
      },

      clearNotifications: () => set({ notifications: [] }),

      removeToast: (id) => {
        const key = String(id || '')
        if (!key) return
        set((state) => ({ toasts: state.toasts.filter((t) => t.id !== key) }))
      },
      clearToasts: () => set({ toasts: [] }),

      // Back-compat aliases.
      push: (n) => get().addNotification(n),
      remove: (id) => get().removeNotification(id),
      clear: () => get().clearNotifications(),
      pushToast: (t) => get().addToast(t),
    }),
    {
      name: 'notifications',
      partialize: (state) => ({ notifications: state.notifications }),
    }
  )
)
