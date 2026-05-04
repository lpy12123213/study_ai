import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types'

interface AuthState {
  user: User | null
  token: string | null
  expiresAt: number | null
  isAuthenticated: boolean
  login: (user: User, token: string, expiresAt?: number | null) => void
  logout: () => void
  clearAuth: () => void
  updateUser: (user: Partial<User>) => void
  isTokenExpired: () => boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      expiresAt: null,
      isAuthenticated: false,
      login: (user, token, expiresAt = null) => {
        set({ user, token, expiresAt, isAuthenticated: true })
      },
      logout: () => {
        set({ user: null, token: null, expiresAt: null, isAuthenticated: false })
      },
      clearAuth: () => {
        set({ user: null, token: null, expiresAt: null, isAuthenticated: false })
      },
      updateUser: (userData) => {
        const currentUser = get().user
        if (currentUser) {
          set({ user: { ...currentUser, ...userData } })
        }
      },
      isTokenExpired: () => {
        const expiresAt = get().expiresAt
        if (!expiresAt) return false
        return Date.now() >= Number(expiresAt) * 1000
      },
    }),
    {
      name: 'auth-storage',
      version: 4,
      migrate: (persistedState: unknown) => {
        const state = (persistedState || {}) as Partial<AuthState>
        const token = typeof state.token === 'string' ? state.token : null
        const expiresAt = typeof state.expiresAt === 'number' ? state.expiresAt : null

        if (!token || token === 'guest-token' || token === 'local-session') {
          return { user: null, token: null, expiresAt: null, isAuthenticated: false }
        }

        return {
          ...state,
          token,
          expiresAt,
          user: state.user || null,
          isAuthenticated: Boolean(state.user && token),
        }
      },
    }
  )
)
