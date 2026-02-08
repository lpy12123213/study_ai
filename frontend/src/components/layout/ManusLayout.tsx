import { Outlet, useLocation } from 'react-router-dom'
import { HistorySidebar } from './HistorySidebar'
import { TaskPanel } from './TaskPanel'
import { Header } from './Header'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn } from '@/lib/utils'

// Pages that show the task panel
const TASK_PANEL_PAGES = ['/chat', '/blueprint', '/study-materials', '/lesson-plans']

export function ManusLayout() {
  const location = useLocation()
  const activeTasks = useTaskStore((state) => state.activeTasks)
  
  // Check if current page should show task panel
  const showTaskPanel = TASK_PANEL_PAGES.some((path) =>
    location.pathname.startsWith(path)
  )
  
  // Check if there are active running tasks
  const hasActiveTasks = Array.from(activeTasks.values()).some((steps) =>
    steps.some((s) => s.status === 'running')
  )
  
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
        
        {/* Right panel - Task timeline */}
        {showTaskPanel && hasActiveTasks && (
          <div className="w-[360px] border-l border-border bg-sidebar-background flex-shrink-0">
            <TaskPanel />
          </div>
        )}
      </div>
    </div>
  )
}
