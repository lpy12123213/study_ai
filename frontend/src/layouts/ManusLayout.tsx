import { useLocation, Outlet } from 'react-router-dom'
import { Header } from './Header'
import { HistorySidebar } from './HistorySidebar'

const FULLSCREEN_ROUTES = ['/canvas']
const STUDIO_ROUTES = ['/question-library', '/ai-generate']
const WIDE_ROUTES = ['/blueprint', '/lesson-plans', '/study-materials', '/question-evaluate', '/deepthink', '/tasks']

export function ManusLayout() {
  const { pathname } = useLocation()

  if (FULLSCREEN_ROUTES.some((r) => pathname.startsWith(r))) {
    return <Outlet />
  }

  const isStudio = STUDIO_ROUTES.some((r) => pathname.startsWith(r))
  const isWide = WIDE_ROUTES.some((r) => pathname.startsWith(r))

  return (
    <div className="flex flex-col h-screen">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        {!isStudio && <HistorySidebar />}
        <main className="flex-1 overflow-y-auto">
          <div className={isWide || isStudio ? 'h-full' : 'max-w-4xl mx-auto px-4 py-6'}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
