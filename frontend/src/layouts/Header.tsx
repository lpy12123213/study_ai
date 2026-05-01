import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Moon, Sun, Settings, User, Menu, X } from 'lucide-react'
import { useAuthStore } from '@/stores/useAuthStore'
import { useThemeStore } from '@/stores/useThemeStore'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { label: '对话', path: '/chat' },
  { label: '深度解题', path: '/deepthink' },
  { label: '蓝图组卷', path: '/blueprint' },
  { label: '自学资料', path: '/study-materials' },
  { label: '好题鉴别', path: '/question-evaluate' },
  { label: '本地题库', path: '/question-library' },
  { label: 'AI出题', path: '/ai-generate' },
  { label: '试卷管理', path: '/papers' },
  { label: '学习画布', path: '/canvas' },
]

export function Header() {
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const { theme, toggleTheme } = useThemeStore()
  const [menuOpen, setMenuOpen] = useState(false)
  const [dropdownOpen, setDropdownOpen] = useState(false)

  return (
    <>
      <header className="sticky top-0 z-40 h-12 border-b bg-background/95 backdrop-blur-sm flex items-center px-4 gap-3">
        <Link to="/dashboard" className="font-bold text-sm tracking-tight shrink-0 mr-2">
          试卷助手
        </Link>

        <nav className="hidden lg:flex items-center gap-0.5 flex-1 overflow-x-auto scrollbar-none">
          {NAV_ITEMS.map((item) => {
            const active = location.pathname.startsWith(item.path)
            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  'px-3 py-1.5 rounded-md text-sm whitespace-nowrap transition-colors',
                  active
                    ? 'bg-foreground text-background font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                )}
              >
                {item.label}
              </Link>
            )
          })}
        </nav>

        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={toggleTheme}
            className="p-2 rounded-md hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          >
            {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </button>

          <div className="relative">
            <button
              onClick={() => setDropdownOpen((o) => !o)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md hover:bg-accent transition-colors text-sm"
            >
              <span className="w-6 h-6 rounded-full bg-foreground text-background flex items-center justify-center text-xs font-bold">
                {user?.username?.[0]?.toUpperCase() ?? <User size={12} />}
              </span>
              <span className="hidden sm:inline text-sm">{user?.username}</span>
            </button>
            {dropdownOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setDropdownOpen(false)} />
                <div className="absolute right-0 top-full mt-1.5 w-44 bg-popover border rounded-lg shadow-lg z-50 py-1 overflow-hidden">
                  <Link
                    to="/settings"
                    onClick={() => setDropdownOpen(false)}
                    className="flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-accent transition-colors"
                  >
                    <Settings size={14} className="text-muted-foreground" /> 设置
                  </Link>
                </div>
              </>
            )}
          </div>

          <button
            className="lg:hidden p-2 rounded-md hover:bg-accent transition-colors"
            onClick={() => setMenuOpen((o) => !o)}
          >
            {menuOpen ? <X size={16} /> : <Menu size={16} />}
          </button>
        </div>
      </header>

      {menuOpen && (
        <div className="lg:hidden border-b bg-background px-4 py-2 flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              onClick={() => setMenuOpen(false)}
              className={cn(
                'px-3 py-2 rounded-md text-sm transition-colors',
                location.pathname.startsWith(item.path)
                  ? 'bg-foreground text-background font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent'
              )}
            >
              {item.label}
            </Link>
          ))}
        </div>
      )}
    </>
  )
}
