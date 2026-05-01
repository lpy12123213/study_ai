import { Outlet, useLocation } from 'react-router-dom'
import { HistorySidebar } from './HistorySidebar'
import { Header } from './Header'
import { CommandPalette } from '@/components/shared/CommandPalette'
import { cn } from '@/lib/utils'
import { useAppearanceStore } from '@/stores/useAppearanceStore'

export function ManusLayout() {
  const location = useLocation()
  const { contentLayout, sidebarPosition } = useAppearanceStore()
  
  // Full screen pages (no sidebar)
  const isFullScreenPage = location.pathname.startsWith('/canvas')

  // Studio pages (keep header, hide history sidebar, manage internal scroll)
  const isStudioPage =
    location.pathname.startsWith('/question-library') ||
    location.pathname.startsWith('/ai-generate')
  
  // Wide pages (no max-width constraint)
  const isWidePage =
    location.pathname.startsWith('/blueprint') ||
    location.pathname.startsWith('/lesson-plans') ||
    location.pathname.startsWith('/study-materials') ||
    location.pathname.startsWith('/knowledge-videos') ||
    location.pathname.startsWith('/question-evaluate') ||
    location.pathname.startsWith('/deepthink') ||
    location.pathname.startsWith('/tasks') ||
    isStudioPage

  const pageManagesOwnScroll =
    location.pathname.startsWith('/study-materials') || location.pathname.startsWith('/knowledge-videos') || location.pathname.startsWith('/lesson-plans') || location.pathname.startsWith('/tasks') || isStudioPage

  const contentWidthClass =
    contentLayout === 'full' ? 'w-full' : contentLayout === 'compact' ? 'max-w-3xl w-full' : 'max-w-4xl w-full'

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
      <CommandPalette />
      
      {/* Main content */}
      <div className={cn('flex-1 flex overflow-hidden', sidebarPosition === 'right' && 'flex-row-reverse')}>
        {/* Left sidebar - History */}
        {!isStudioPage && <HistorySidebar />}
        
        {/* Center - Main content */}
        <main className="flex-1 flex flex-col overflow-hidden relative bg-background">
          <div className={cn('flex-1 min-h-0', pageManagesOwnScroll ? 'overflow-hidden' : 'overflow-auto')}>
            <div className={cn(
              "h-full mx-auto",
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
