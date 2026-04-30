import { useState, useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Plus, PenSquare } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { chatApi } from '@/api/chat'
import { cn } from '@/lib/utils'

const SCOPE_MAP: Record<string, string> = {
  '/chat': 'chat',
  '/blueprint': 'blueprint',
  '/lesson-plans': 'lesson_plan',
  '/study-materials': 'study_materials',
}

function getScope(pathname: string) {
  for (const [prefix, scope] of Object.entries(SCOPE_MAP)) {
    if (pathname.startsWith(prefix)) return scope
  }
  return 'chat'
}

export function HistorySidebar() {
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('manus.sidebar.collapsed') === 'true' } catch { return false }
  })

  useEffect(() => {
    const onResize = () => { if (window.innerWidth < 1024) setCollapsed(true) }
    window.addEventListener('resize', onResize)
    onResize()
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    localStorage.setItem('manus.sidebar.collapsed', String(collapsed))
  }, [collapsed])

  const scope = getScope(location.pathname)
  const { data } = useQuery({
    queryKey: ['conversations', scope],
    queryFn: () => chatApi.getConversations(scope).then((r) => r.data),
  })
  const conversations: { id: string; title: string }[] = data?.conversations ?? data ?? []

  if (collapsed) {
    return (
      <aside className="flex flex-col items-center w-[52px] bg-sidebar border-r py-3 gap-2 shrink-0">
        <button onClick={() => setCollapsed(false)} className="p-2 rounded-lg hover:bg-sidebar-accent transition-colors text-sidebar-foreground/60 hover:text-sidebar-foreground">
          <PenSquare size={16} />
        </button>
        <Link to="/chat" className="p-2 rounded-lg hover:bg-sidebar-accent transition-colors text-sidebar-foreground/60 hover:text-sidebar-foreground">
          <Plus size={16} />
        </Link>
      </aside>
    )
  }

  return (
    <aside className="flex flex-col w-[260px] bg-sidebar border-r shrink-0">
      {/* Top bar */}
      <div className="flex items-center justify-between px-3 py-3">
        <button onClick={() => setCollapsed(true)} className="p-1.5 rounded-lg hover:bg-sidebar-accent transition-colors text-sidebar-foreground/60 hover:text-sidebar-foreground">
          <PenSquare size={16} />
        </button>
        <Link to="/chat" className="p-1.5 rounded-lg hover:bg-sidebar-accent transition-colors text-sidebar-foreground/60 hover:text-sidebar-foreground">
          <Plus size={16} />
        </Link>
      </div>

      {/* History list */}
      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {conversations.length > 0 && (
          <div className="mb-1">
            <p className="px-2 py-1 text-xs font-medium text-sidebar-foreground/40">最近</p>
            {conversations.map((conv) => (
              <Link
                key={conv.id}
                to={`/chat/${conv.id}`}
                className={cn(
                  'block px-3 py-2 rounded-lg text-sm truncate transition-colors',
                  location.pathname === `/chat/${conv.id}`
                    ? 'bg-sidebar-accent text-sidebar-foreground font-medium'
                    : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground'
                )}
              >
                {conv.title || '新对话'}
              </Link>
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}
