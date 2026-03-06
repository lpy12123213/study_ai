import { Outlet, useLocation } from 'react-router-dom'
import { HistorySidebar } from './HistorySidebar'
import { Header } from './Header'
import { cn } from '@/lib/utils'

export function ManusLayout() {
  const location = useLocation()
  
  // Full screen pages (no sidebar)
  const isFullScreenPage = location.pathname.startsWith('/canvas')

  // Studio pages (keep header, hide history sidebar, manage internal scroll)
  const isStudioPage = location.pathname.startsWith('/question-library')
  
  // Wide pages (no max-width constraint)
  const isWidePage =
    location.pathname.startsWith('/blueprint') ||
    location.pathname.startsWith('/lesson-plans') ||
    location.pathname.startsWith('/study-materials') ||
    location.pathname.startsWith('/question-evaluate') ||
    location.pathname.startsWith('/deepthink') ||
    isStudioPage

  const pageManagesOwnScroll =
    location.pathname.startsWith('/study-materials') || location.pathname.startsWith('/lesson-plans') || isStudioPage

  if (isFullScreenPage) {
    return (
      <div className="h-screen w-screen overflow-hidden bg-background text-foreground">
        <Outlet />
      </div>
    )
  }

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-background text-foreground">
      {/* Header */}
      <Header />
      
      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left sidebar - History */}
        {!isStudioPage && <HistorySidebar />}
        
        {/* Center - Main content */}
        <main className="flex-1 flex flex-col overflow-hidden relative bg-background">
          <div className={cn('flex-1 min-h-0', pageManagesOwnScroll ? 'overflow-hidden' : 'overflow-auto')}>
            <div className={cn(
              "h-full mx-auto",
              !isWidePage && "max-w-4xl w-full"
            )}>
               <Outlet />
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
