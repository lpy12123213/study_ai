import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

type NavigateEventDetail = {
  to: string
  replace?: boolean
  state?: unknown
}

const NAVIGATE_EVENT = 'app:navigate'

export function NavigationEventHost() {
  const navigate = useNavigate()

  useEffect(() => {
    const handler = (evt: Event) => {
      const detail = (evt as CustomEvent<NavigateEventDetail>)?.detail
      const to = typeof detail?.to === 'string' ? detail.to : ''
      if (!to) return
      navigate(to, { replace: Boolean(detail?.replace), state: detail?.state })
    }

    window.addEventListener(NAVIGATE_EVENT, handler as EventListener)
    return () => window.removeEventListener(NAVIGATE_EVENT, handler as EventListener)
  }, [navigate])

  return null
}
