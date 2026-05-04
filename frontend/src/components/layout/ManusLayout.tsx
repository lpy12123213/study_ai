import { useEffect, useRef } from 'react'
import { Outlet, useLocation, useMatches } from 'react-router-dom'
import { HistorySidebar } from './HistorySidebar'
import { Header } from './Header'
import { SubHeader } from './SubHeader'
import { CommandPalette } from '@/components/shared/CommandPalette'
import { NotificationCenter } from '@/components/shared/NotificationCenter'
import { ToastHost } from '@/components/shared/ToastHost'
import { cn } from '@/lib/utils'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useLayoutPrefs } from '@/hooks/useLayoutPrefs'
import { useI18n } from '@/i18n'
import { getRouteConfigFromMatches, matchRouteConfig } from '@/router/routes.config'

export function ManusLayout() {
  const location = useLocation()
  const matches = useMatches()
  const { contentLayout, sidebarPosition } = useLayoutPrefs()
  const { routeLabel, t } = useI18n()
  const mainRef = useRef<HTMLElement | null>(null)
  const previousLocationKey = useRef(location.key)
  const routeConfig = getRouteConfigFromMatches(matches) || matchRouteConfig(location.pathname)
  const isFullScreenPage = routeConfig.layout === 'fullscreen'
  const isWidePage = routeConfig.layout === 'wide' || routeConfig.layout === 'studio'
  const pageTitle = routeLabel(routeConfig.id, routeConfig.title)
  useDocumentTitle(pageTitle)

  const contentWidthClass =
    contentLayout === 'full' ? 'w-full' : contentLayout === 'compact' ? 'max-w-4xl w-full' : 'max-w-6xl w-full'

  useEffect(() => {
    if (previousLocationKey.current === location.key) return
    previousLocationKey.current = location.key
    mainRef.current?.focus({ preventScroll: true })
  }, [location.key])

  if (isFullScreenPage) {
    return (
      <div className="h-screen w-screen overflow-hidden bg-background text-foreground">
        <div className="fixed right-4 top-4 z-[60] rounded-md border border-border bg-background/90 shadow-sm backdrop-blur">
          <NotificationCenter />
        </div>
        <CommandPalette />
        <ToastHost />
        <Outlet />
      </div>
    )
  }

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-background text-foreground">
      <a
        href="#main"
        className="sr-only z-[60] rounded-md bg-background px-3 py-2 text-sm font-medium text-foreground ring-1 ring-ring focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        {t('layout.skipToMain')}
      </a>
      {/* Header */}
      <Header notificationSlot={<NotificationCenter />} />
      <SubHeader />
      <CommandPalette />
      <ToastHost />
      
      {/* Main content */}
      <div className={cn('flex flex-1 overflow-hidden', sidebarPosition === 'right' && 'flex-row-reverse')}>
        {/* Left sidebar - History */}
        {routeConfig.sidebar && <HistorySidebar />}
        
        {/* Center - Main content */}
        <main
          id="main"
          ref={mainRef}
          tabIndex={-1}
          className="relative flex flex-1 flex-col overflow-hidden bg-background outline-none"
        >
          <div className="flex-1 min-h-0 overflow-auto">
            <div className={cn(
              "mx-auto h-full",
              !isWidePage && contentWidthClass
            )}>
               <Outlet />
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
