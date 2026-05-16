import { useEffect } from 'react'
import { getCurrentUser } from '@/api/auth'
import { useAuthStore } from '@/stores/useAuthStore'

export function AuthBootstrap() {
  useEffect(() => {
    let cancelled = false

    const run = async () => {
      try {
        const user = await getCurrentUser()
        if (!cancelled) {
          useAuthStore.getState().restoreSession(user)
        }
      } catch {
        if (!cancelled) {
          useAuthStore.getState().clearAuth()
        }
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [])

  return null
}
