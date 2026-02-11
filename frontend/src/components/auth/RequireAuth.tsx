import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/useAuthStore'

export function RequireAuth() {
  const location = useLocation()
  const { isAuthenticated, token } = useAuthStore()

  if (!isAuthenticated || !token) {
    const from = `${location.pathname}${location.search}`
    return <Navigate to="/login" replace state={{ from }} />
  }

  return <Outlet />
}

