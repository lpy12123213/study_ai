import { useEffect, useRef } from 'react'
import { Outlet, useLocation, useMatches } from 'react-router-dom'
import { HistorySidebar } from './HistorySidebar'
import { Header } from './Header'
import { SubHeader } from './SubHeader'
import { CommandPalette } from '@/components/shared/CommandPalette'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'
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
      <div className="aurora-app-shell aurora-app-shell-fullscreen h-screen w-screen overflow-hidden text-foreground">
        <div className="aurora-shell-floating-control fixed right-4 top-4 z-[60] rounded-md">
          <NotificationCenter />
        </div>
        <CommandPalette />
        <ToastHost />
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </div>
    )
  }

  return (
    <div className="aurora-app-shell aurora-app-shell-framed flex h-screen w-screen flex-col overflow-hidden text-foreground">
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
          className="aurora-main-stage relative flex flex-1 flex-col overflow-hidden outline-none"
        >
          <div className="aurora-main-scroll flex-1 min-h-0 overflow-auto">
            <div className={cn(
              "aurora-main-content mx-auto h-full",
              !isWidePage && contentWidthClass
            )}>
               <ErrorBoundary key={location.pathname}>
                 <Outlet />
               </ErrorBoundary>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
