import { Outlet, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { HistorySidebar } from './HistorySidebar'
import { TaskPanel } from './TaskPanel'
import { Header } from './Header'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn } from '@/lib/utils'

// Pages that show the task panel
const TASK_PANEL_PAGES = ['/chat', '/blueprint', '/study-materials']

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

  if (isFullScreenPage) {
    return (
      <div className="h-screen w-screen overflow-hidden">
        <Outlet />
      </div>
    )
  }

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-background">
      {/* Header */}
      <Header />
      
      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left sidebar - History */}
        <HistorySidebar />
        
        {/* Center - Main content */}
        <main className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-auto">
            <Outlet />
          </div>
        </main>
        
        {/* Right panel - Task timeline */}
        <AnimatePresence mode="wait">
          {showTaskPanel && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: hasActiveTasks ? 360 : 0, opacity: hasActiveTasks ? 1 : 0 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: 'easeInOut' }}
              className={cn(
                "border-l border-border overflow-hidden",
                !hasActiveTasks && "hidden"
              )}
            >
              <TaskPanel />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
