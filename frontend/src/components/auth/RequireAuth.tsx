import { useEffect } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/useAuthStore'

export function useRequireAuth(): boolean {
  const { isAuthenticated, token, isTokenExpired, logout } = useAuthStore()
  const valid = Boolean(isAuthenticated && token && !isTokenExpired())
  useEffect(() => {
    if (!valid && (isAuthenticated || token)) {
      logout()
    }
  }, [isAuthenticated, logout, token, valid])
  return valid
}

export function RequireAuth() {
  const location = useLocation()
  const valid = useRequireAuth()
  if (!valid) {
    const redirect = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to={`/login?redirect=${encodeURIComponent(redirect)}`} replace />
  }
  return <Outlet />
}

