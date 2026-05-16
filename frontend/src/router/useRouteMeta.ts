import { useLocation, useMatches } from 'react-router-dom'
import { getRouteConfigFromMatches, matchRouteConfig } from '@/router/routes.config'

export function useRouteMeta() {
  const location = useLocation()
  const matches = useMatches()

  return getRouteConfigFromMatches(matches) || matchRouteConfig(location.pathname)
}
