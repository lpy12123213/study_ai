import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types'

const LOCAL_USER: User = {
  id: 'local-user',
  username: '本地用户',
  role: 'admin',
}

const LOCAL_TOKEN = 'local-session'

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  login: (user: User, token: string) => void
  logout: () => void
  clearAuth: () => void
  updateUser: (user: Partial<User>) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: LOCAL_USER,
      token: LOCAL_TOKEN,
      isAuthenticated: true,
      login: (user, token) => {
        set({ user, token, isAuthenticated: true })
      },
      logout: () => {
        set({ user: LOCAL_USER, token: LOCAL_TOKEN, isAuthenticated: true })
      },
      clearAuth: () => {
        set({ user: LOCAL_USER, token: LOCAL_TOKEN, isAuthenticated: true })
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
      version: 3,
      migrate: (persistedState: unknown) => {
        const state = (persistedState || {}) as Partial<AuthState>
        const token = typeof state.token === 'string' ? state.token : null

        if (!token || token === 'guest-token') {
          return { user: LOCAL_USER, token: LOCAL_TOKEN, isAuthenticated: true }
        }

        return {
          ...state,
          token,
          user: state.user || LOCAL_USER,
          isAuthenticated: true,
        }
      },
    }
  )
)
