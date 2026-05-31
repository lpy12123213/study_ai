import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from '@/components/ui/command'
import {
  Monitor,
  Plus,
  type LucideIcon,
} from 'lucide-react'
import { COMMAND_ROUTE_ITEMS, getRouteConfig } from '@/router/routes.config'
import { useThemeStore } from '@/stores/useThemeStore'
import { useI18n } from '@/i18n'

type CommandEntry = {
  id: string
  title: string
  subtitle?: string
  icon?: LucideIcon
  shortcut?: string
  run: () => void
}

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = String(el.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  return Boolean(el.getAttribute?.('contenteditable') === 'true')
}

export function CommandPalette() {
  const navigate = useNavigate()
  const toggleTheme = useThemeStore((state) => state.toggleTheme)
  const { routeLabel, t } = useI18n()
  const [open, setOpen] = useState(false)
  const [showShortcuts, setShowShortcuts] = useState(false)

  const { routeCommands, actionCommands } = useMemo<{
    routeCommands: CommandEntry[]
    actionCommands: CommandEntry[]
  }>(() => {
    const go = (path: string) => () => {
      setOpen(false)
      navigate(path)
    }
    const action = (id: string, title: string, path: string, icon: CommandEntry['icon'], subtitle?: string): CommandEntry => ({
      id,
      title,
      subtitle: subtitle || path,
      icon,
      run: go(path),
    })

    const routeCommands = COMMAND_ROUTE_ITEMS.map((route) => ({
      id: `nav-${route.id}`,
      title: routeLabel(route.id, route.label),
      subtitle: route.path,
      icon: route.icon,
      shortcut: route.path === '/search' ? 'Ctrl K' : undefined,
      run: go(route.path),
    }))

    return {
      routeCommands,
    actionCommands: [
      action('action-new-chat', t('command.newChat'), '/chat', Plus),
      action('action-new-blueprint', t('command.newBlueprint'), '/blueprint', getRouteConfig('/blueprint')?.icon),
      action('action-new-lesson-plan', t('command.newLessonPlan'), '/lesson-plans', getRouteConfig('/lesson-plans')?.icon),
      action('action-new-study-material', t('command.newStudyMaterial'), '/study-materials', getRouteConfig('/study-materials')?.icon),
      action('action-open-question-library', t('command.openQuestionLibrary'), '/question-library', getRouteConfig('/question-library')?.icon),
      {
        id: 'action-toggle-theme',
        title: t('command.toggleTheme'),
        subtitle: t('command.themeSubtitle'),
        icon: Monitor,
        run: () => {
          toggleTheme()
          setOpen(false)
        },
      },
      {
        id: 'action-show-shortcuts',
        title: t('command.showShortcuts'),
        subtitle: 'Ctrl/⌘ + /',
        icon: Monitor,
        shortcut: 'Ctrl /',
        run: () => {
          setShowShortcuts(true)
        },
      },
    ],
  }
  }, [navigate, routeLabel, t, toggleTheme])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const key = String(e.key || '').toLowerCase()
      const ctrlOrMeta = e.ctrlKey || e.metaKey
      if (ctrlOrMeta && key === 'k') {
        e.preventDefault()
        setShowShortcuts(false)
        if (isTypingTarget(e.target) && !open) {
          // Avoid hijacking common IME/search shortcuts when typing heavily. Still allow opening when already open.
          setOpen(true)
          return
        }
        setOpen((v) => !v)
      }
      if (ctrlOrMeta && e.key === '/') {
        e.preventDefault()
        setShowShortcuts(true)
        setOpen(true)
      }
      if (key === 'escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  return (
    <>
      <div aria-live="polite" className="sr-only">
        {open ? t('command.paletteOpen') : t('command.paletteClosed')}
      </div>
      <CommandDialog open={open} onOpenChange={setOpen}>
        <CommandInput aria-label={t('command.searchPlaceholder')} placeholder={t('command.searchPlaceholder')} />
        <CommandList>
          <CommandEmpty>{t('command.noResults')}</CommandEmpty>
          <CommandGroup heading={t('command.navigation')}>
            {routeCommands.map((c) => {
              const Icon = c.icon
              return (
                <CommandItem key={c.id} onSelect={c.run}>
                  {Icon && <Icon className="mr-2 h-4 w-4 opacity-70" />}
                  <span>{c.title}</span>
                  {c.subtitle && <span className="ml-2 text-xs text-muted-foreground">{c.subtitle}</span>}
                  {c.shortcut && <CommandShortcut>{c.shortcut}</CommandShortcut>}
                </CommandItem>
              )
            })}
          </CommandGroup>
          <CommandSeparator />
          <CommandGroup heading={t('command.actions')}>
            {actionCommands.map((c) => {
              const Icon = c.icon
              return (
                <CommandItem key={c.id} onSelect={c.run}>
                  {Icon && <Icon className="mr-2 h-4 w-4 opacity-70" />}
                  <span>{c.title}</span>
                  {c.subtitle && <span className="ml-2 text-xs text-muted-foreground">{c.subtitle}</span>}
                  {c.shortcut && <CommandShortcut>{c.shortcut}</CommandShortcut>}
                </CommandItem>
              )
            })}
          </CommandGroup>
          <CommandSeparator />
          {showShortcuts ? (
            <CommandGroup heading={t('command.shortcuts')}>
              <CommandItem disabled>
                <span className="text-xs text-muted-foreground">{t('command.openPalette')}</span>
                <CommandShortcut>Ctrl/⌘ K</CommandShortcut>
              </CommandItem>
              <CommandItem disabled>
                <span className="text-xs text-muted-foreground">{t('command.openShortcutHelp')}</span>
                <CommandShortcut>Ctrl/⌘ /</CommandShortcut>
              </CommandItem>
              <CommandItem disabled>
                <span className="text-xs text-muted-foreground">{t('command.closePalette')}</span>
                <CommandShortcut>Esc</CommandShortcut>
              </CommandItem>
            </CommandGroup>
          ) : (
            <CommandGroup heading={t('command.tips')}>
              <CommandItem disabled>
                <span className="text-xs text-muted-foreground">{t('command.shortcutHint')}</span>
              </CommandItem>
            </CommandGroup>
          )}
        </CommandList>
      </CommandDialog>
    </>
  )
}
