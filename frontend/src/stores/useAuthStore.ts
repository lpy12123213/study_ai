import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types'

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  login: (user: User, token: string) => void
  logout: () => void
  updateUser: (user: Partial<User>) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      login: (user, token) => {
        set({ user, token, isAuthenticated: true })
      },
      logout: () => {
        set({ user: null, token: null, isAuthenticated: false })
      },
      updateUser: (userData) => {
        const currentUser = get().user
        if (currentUser) {
          set({ user: { ...currentUser, ...userData } })
        }
      },
    }),
    {
      name: 'auth-storage',
      version: 2,
      migrate: (persistedState: unknown) => {
        const state = (persistedState || {}) as Partial<AuthState>
        const token = typeof state.token === 'string' ? state.token : null

        // Drop legacy "guest" sessions: chat now requires a real JWT login.
        if (token === 'guest-token') {
          return { user: null, token: null, isAuthenticated: false }
        }

        return {
          ...state,
          token,
          isAuthenticated: Boolean(token),
        }
      },
    }
  )
)
