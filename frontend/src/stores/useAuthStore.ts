import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types'

const LOCAL_USER: User = {
  id: 'local-user',
  username: '本地用户',
  role: 'admin',
}

const LOCAL_SESSION_TOKEN = 'local-session'

function localAuthState() {
  return {
    user: LOCAL_USER,
    token: LOCAL_SESSION_TOKEN,
    expiresAt: null,
    isAuthenticated: true,
  }
}

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
      ...localAuthState(),
      login: (user, token, expiresAt = null) => {
        set({ user: user || LOCAL_USER, token: token || LOCAL_SESSION_TOKEN, expiresAt, isAuthenticated: true })
      },
      logout: () => {
        set(localAuthState())
      },
      clearAuth: () => {
        set(localAuthState())
      },
      updateUser: (userData) => {
        const currentUser = get().user
        if (currentUser) {
          set({ user: { ...currentUser, ...userData } })
        }
      },
      isTokenExpired: () => {
        if (get().token === LOCAL_SESSION_TOKEN) return false
        const expiresAt = get().expiresAt
        if (!expiresAt) return false
        return Date.now() >= Number(expiresAt) * 1000
      },
    }),
    {
      name: 'auth-storage',
      version: 5,
      migrate: () => localAuthState(),
    }
  )
)
