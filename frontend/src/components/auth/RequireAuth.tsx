import { Outlet } from 'react-router-dom'
import { useAuthStore } from '@/stores/useAuthStore'

export function useRequireAuth(): boolean {
  return useAuthStore((s) => Boolean(s.isAuthenticated && !s.isTokenExpired()))
}

export function RequireAuth() {
  return <Outlet />
}

