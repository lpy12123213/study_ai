import { Link, useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  MessagesSquare,
  Brain,
  Files,
  LayoutTemplate,
  BookOpen,
  Library,
  Award,
  PenTool,
  Settings,
  LogOut,
  Monitor,
  Moon,
  Sun,
  Menu,
} from 'lucide-react'
import { BrandMark } from '@/components/shared/BrandMark'
import { useAuthStore } from '@/stores/useAuthStore'
import { useThemeStore } from '@/stores/useThemeStore'
import { cn } from '@/lib/utils'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from '@/components/ui/dropdown-menu'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'

const navItems = [
  { path: '/chat', label: '对话', icon: MessagesSquare },
  { path: '/deepthink', label: '深度解题', icon: Brain },
  { path: '/blueprint', label: '蓝图组卷', icon: LayoutTemplate },
  { path: '/study-materials', label: '自学资料', icon: BookOpen },
  { path: '/question-evaluate', label: '好题鉴别', icon: Award },
  { path: '/question-library', label: '本地题库', icon: Library },
  { path: '/papers', label: '试卷管理', icon: Files },
  { path: '/canvas', label: '学习画布', icon: PenTool },
]

export function Header() {
  const location = useLocation()
  const navigate = useNavigate()
  const { setTheme, theme } = useThemeStore()
  const { user, isAuthenticated, logout } = useAuthStore()

  const initials = (user?.username || 'U').slice(0, 1).toUpperCase()

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="h-12 border-b border-border bg-background/80 backdrop-blur-sm sticky top-0 z-50 flex items-center justify-between px-4">
      {/* Logo */}
      <Link to="/chat" className="flex items-center gap-2">
        <BrandMark size={24} />
        <span className="font-semibold text-sm tracking-tight">学习助手</span>
      </Link>

      {/* Navigation */}
      <nav className="hidden lg:flex items-center gap-6">
        {navItems.map((item) => {
          const isActive = location.pathname.startsWith(item.path)
          
          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                'relative py-1.5 text-sm font-medium transition-colors hover:text-foreground/80',
                isActive ? 'text-foreground' : 'text-muted-foreground'
              )}
            >
              {item.label}
              {isActive && (
                <motion.div
                  layoutId="header-nav-underline"
                  className="absolute left-0 right-0 -bottom-[13px] h-[2px] bg-foreground"
                  transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                />
              )}
            </Link>
          )
        })}
      </nav>

      {/* Right actions */}
      <div className="flex items-center gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            {navItems.map((item) => {
              const isActive = location.pathname.startsWith(item.path)
              const Icon = item.icon
              return (
                <DropdownMenuItem key={item.path} asChild>
                  <Link
                    to={item.path}
                    className={cn(
                      'cursor-pointer w-full flex items-center',
                      isActive ? 'text-foreground' : 'text-muted-foreground'
                    )}
                  >
                    <Icon className="mr-2 h-4 w-4" />
                    <span>{item.label}</span>
                  </Link>
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <div className="cursor-pointer">
              <Avatar className="h-8 w-8 transition-opacity hover:opacity-80">
                <AvatarImage src="" />
                <AvatarFallback className="text-xs">{initials}</AvatarFallback>
              </Avatar>
            </div>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>{isAuthenticated && user ? user.username : '未登录'}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {!isAuthenticated && (
              <DropdownMenuItem asChild>
                <Link to="/login" className="cursor-pointer w-full flex items-center">
                  <MessagesSquare className="mr-2 h-4 w-4" />
                  <span>去登录</span>
                </Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem asChild>
              <Link to="/settings" className="cursor-pointer w-full flex items-center">
                <Settings className="mr-2 h-4 w-4" />
                <span>设置</span>
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <Monitor className="mr-2 h-4 w-4" />
                <span>主题</span>
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                <DropdownMenuItem onClick={() => setTheme('light')}>
                  <Sun className="mr-2 h-4 w-4" />
                  <span>浅色</span>
                  {theme === 'light' && <span className="ml-auto text-xs">✓</span>}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTheme('dark')}>
                  <Moon className="mr-2 h-4 w-4" />
                  <span>深色</span>
                  {theme === 'dark' && <span className="ml-auto text-xs">✓</span>}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTheme('system')}>
                  <Monitor className="mr-2 h-4 w-4" />
                  <span>跟随系统</span>
                  {theme === 'system' && <span className="ml-auto text-xs">✓</span>}
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
            <DropdownMenuSeparator />
            {isAuthenticated && (
              <DropdownMenuItem
                className="text-destructive focus:text-destructive cursor-pointer"
                onClick={handleLogout}
              >
                <LogOut className="mr-2 h-4 w-4" />
                <span>退出登录</span>
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
