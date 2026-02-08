import { Link, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  MessagesSquare,
  Files,
  LayoutTemplate,
  BookOpen,
  BookOpenCheck,
  PenTool,
  Settings2,
} from 'lucide-react'
import { BrandMark } from '@/components/shared/BrandMark'
import { ThemeToggle } from '@/components/shared/ThemeToggle'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const navItems = [
  { path: '/chat', label: '对话', icon: MessagesSquare },
  { path: '/blueprint', label: '蓝图组卷', icon: LayoutTemplate },
  { path: '/lesson-plans', label: '教案生成', icon: BookOpenCheck },
  { path: '/study-materials', label: '自学资料', icon: BookOpen },
  { path: '/papers', label: '试卷管理', icon: Files },
  { path: '/canvas', label: '学习画布', icon: PenTool },
]

export function Header() {
  const location = useLocation()

  return (
    <header className="h-14 border-b border-border glass glass-border flex items-center justify-between px-4">
      {/* Logo */}
      <Link to="/chat" className="flex items-center gap-2">
        <BrandMark size={32} />
        <div className="leading-tight hidden sm:block">
          <div className="font-semibold text-sm">试卷助手</div>
          <div className="text-xs text-muted-foreground">Manus 式时间轴</div>
        </div>
      </Link>

      {/* Navigation */}
      <nav className="flex items-center">
        <div className="relative flex items-center gap-1 rounded-full bg-muted/40 p-1 ring-1 ring-border/60">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = location.pathname.startsWith(item.path)

            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  'relative flex items-center rounded-full px-3 py-1.5 text-sm transition-colors select-none',
                  isActive
                    ? 'text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                {isActive && (
                  <motion.span
                    layoutId="topNavActive"
                    className="absolute inset-0 rounded-full bg-background/70 shadow-sm"
                    transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                  />
                )}
                <span className="relative z-10 inline-flex items-center gap-2">
                  <Icon className="h-4 w-4" strokeWidth={1.8} />
                  <span className="hidden md:inline">{item.label}</span>
                </span>
              </Link>
            )
          })}
        </div>
      </nav>

      {/* Right actions */}
      <div className="flex items-center gap-2">
        <ThemeToggle />
        <Link to="/settings">
          <Button variant="ghost" size="icon" className="h-9 w-9">
            <Settings2 className="h-4 w-4" strokeWidth={1.8} />
          </Button>
        </Link>
      </div>
    </header>
  )
}
