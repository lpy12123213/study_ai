import { type ReactNode, useRef, useState } from 'react'
import { Link, useLocation, useMatches, useNavigate } from 'react-router-dom'
import {
  Settings,
  Monitor,
  Moon,
  Sun,
  Menu,
  ListChecks,
  Bug,
  Languages,
} from 'lucide-react'
import { BrandMark } from '@/components/shared/BrandMark'
import { FeedbackDialog } from '@/components/shared/FeedbackDialog'
import { getRouteConfigFromMatches, HEADER_NAV_ITEMS, isRouteActive } from '@/router/routes.config'
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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { APP_BRAND_NAME } from '@/constants/branding'
import { useI18n, type Locale } from '@/i18n'

type HeaderProps = {
  notificationSlot?: ReactNode
}

export function Header({ notificationSlot }: HeaderProps) {
  const location = useLocation()
  const matches = useMatches()
  const navigate = useNavigate()
  const { setTheme, theme } = useThemeStore()
  const user = useAuthStore((s) => s.user)
  const { locale, routeLabel, setLocale, t } = useI18n()
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const mobileNavTriggerRef = useRef<HTMLButtonElement | null>(null)
  const userMenuTriggerRef = useRef<HTMLButtonElement | null>(null)

  const initials = (user?.username || 'U').slice(0, 1).toUpperCase()
  const activeRouteConfig = getRouteConfigFromMatches(matches)
  const setLanguage = (nextLocale: Locale) => setLocale(nextLocale)

  return (
    <header className="sticky top-0 z-50 flex h-16 items-center justify-between border-b border-border bg-background px-4 lg:px-6">
      {/* Logo */}
      <Link to="/dashboard" className="flex shrink-0 items-center gap-2">
        <BrandMark size={26} />
        <span className="text-sm font-medium text-foreground">{APP_BRAND_NAME}</span>
      </Link>

      {/* Navigation */}
      <nav className="hidden h-10 items-center gap-1 rounded-lg border border-border bg-card px-1 lg:flex">
        <TooltipProvider delayDuration={250}>
          {HEADER_NAV_ITEMS.map((item) => {
            const isActive =
              activeRouteConfig?.id === item.id ||
              activeRouteConfig?.parentId === item.id ||
              isRouteActive(location.pathname, item.path)
            const Icon = item.icon
            const label = routeLabel(item.id, item.label)

            return (
              <Tooltip key={item.path}>
                <TooltipTrigger asChild>
                  <Link
                    to={item.path}
                    aria-label={label}
                    className={cn(
                      'relative flex h-8 w-8 items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors xl:w-auto xl:px-3',
                      isActive
                        ? 'bg-foreground text-background'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="hidden xl:inline">{label}</span>
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="xl:hidden">
                  {label}
                </TooltipContent>
              </Tooltip>
            )
          })}
        </TooltipProvider>
      </nav>

      {/* Right actions */}
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-9 w-9"
          aria-label={t('header.taskCenter')}
          onClick={() => navigate('/tasks')}
        >
          <ListChecks className="h-4 w-4" />
        </Button>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-9 w-9"
          aria-label={t('header.feedback')}
          onClick={() => setFeedbackOpen(true)}
        >
          <Bug className="h-4 w-4" />
        </Button>

        {notificationSlot}

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              ref={mobileNavTriggerRef}
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9 lg:hidden"
              aria-label={t('header.openNavigation')}
            >
              <Menu className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="w-56"
            onCloseAutoFocus={(event) => {
              event.preventDefault()
              mobileNavTriggerRef.current?.focus()
            }}
          >
            {HEADER_NAV_ITEMS.map((item) => {
              const isActive = isRouteActive(location.pathname, item.path)
              const Icon = item.icon
              const label = routeLabel(item.id, item.label)
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
                    <span>{label}</span>
                  </Link>
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              ref={userMenuTriggerRef}
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              aria-label={t('header.openUserMenu')}
            >
              <Avatar className="h-8 w-8 border border-border transition-opacity hover:opacity-80">
                <AvatarImage src="" />
                <AvatarFallback className="bg-card text-xs text-foreground">{initials}</AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="w-56"
            onCloseAutoFocus={(event) => {
              event.preventDefault()
              userMenuTriggerRef.current?.focus()
            }}
          >
            <DropdownMenuLabel>{user?.username || t('header.localUser')}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/settings" className="cursor-pointer w-full flex items-center">
                <Settings className="mr-2 h-4 w-4" />
                <span>{t('header.settings')}</span>
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <Languages className="mr-2 h-4 w-4" />
                <span>{t('header.language')}</span>
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                <DropdownMenuItem onClick={() => setLanguage('zh-CN')}>
                  <span>{t('header.languageZh')}</span>
                  {locale === 'zh-CN' && <span className="ml-auto text-xs">✓</span>}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setLanguage('en-US')}>
                  <span>{t('header.languageEn')}</span>
                  {locale === 'en-US' && <span className="ml-auto text-xs">✓</span>}
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <Monitor className="mr-2 h-4 w-4" />
                <span>{t('header.theme')}</span>
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                <DropdownMenuItem onClick={() => setTheme('light')}>
                  <Sun className="mr-2 h-4 w-4" />
                  <span>{t('header.themeLight')}</span>
                  {theme === 'light' && <span className="ml-auto text-xs">✓</span>}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTheme('dark')}>
                  <Moon className="mr-2 h-4 w-4" />
                  <span>{t('header.themeDark')}</span>
                  {theme === 'dark' && <span className="ml-auto text-xs">✓</span>}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTheme('system')}>
                  <Monitor className="mr-2 h-4 w-4" />
                  <span>{t('header.themeSystem')}</span>
                  {theme === 'system' && <span className="ml-auto text-xs">✓</span>}
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <FeedbackDialog open={feedbackOpen} onOpenChange={setFeedbackOpen} />
    </header>
  )
}
