import { Outlet, useLocation } from 'react-router-dom'
import { HistorySidebar } from './HistorySidebar'
import { Header } from './Header'
import { cn } from '@/lib/utils'

export function ManusLayout() {
  const location = useLocation()
  
  // Full screen pages (no sidebar)
  const isFullScreenPage = location.pathname.startsWith('/canvas')
  
  // Wide pages (no max-width constraint)
  const isWidePage = location.pathname.startsWith('/blueprint')

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
        <HistorySidebar />
        
        {/* Center - Main content */}
        <main className="flex-1 flex flex-col overflow-hidden relative bg-background">
          <div className="flex-1 overflow-auto">
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
