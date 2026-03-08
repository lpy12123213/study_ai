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
  BarChart3,
  BookOpen,
  Bug,
  Files,
  LayoutTemplate,
  ListChecks,
  ListTodo,
  Search,
  Tag,
  BookX,
  Settings,
} from 'lucide-react'

type CommandEntry = {
  id: string
  title: string
  subtitle?: string
  icon?: any
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
  const [open, setOpen] = useState(false)

  const commands = useMemo<CommandEntry[]>(() => {
    const go = (path: string) => () => {
      setOpen(false)
      navigate(path)
    }
    return [
      { id: 'nav-search', title: '全文搜索', subtitle: '/search', icon: Search, shortcut: 'Ctrl K', run: go('/search') },
      { id: 'nav-tasks', title: '任务中心', subtitle: '/tasks', icon: ListChecks, run: go('/tasks') },
      { id: 'nav-exports', title: '导出中心', subtitle: '/exports', icon: Files, run: go('/exports') },
      { id: 'nav-templates', title: '模板库', subtitle: '/templates', icon: LayoutTemplate, run: go('/templates') },
      { id: 'nav-learning', title: '学习计划', subtitle: '/learning-plans', icon: ListTodo, run: go('/learning-plans') },
      { id: 'nav-wrongbook', title: '错题本', subtitle: '/wrongbook', icon: BookX, run: go('/wrongbook') },
      { id: 'nav-annotations', title: '批注', subtitle: '/annotations', icon: Tag, run: go('/annotations') },
      { id: 'nav-feedback', title: '反馈', subtitle: '/feedback', icon: Bug, run: go('/feedback') },
      { id: 'nav-dashboard', title: '仪表盘', subtitle: '/dashboard', icon: BarChart3, run: go('/dashboard') },
      { id: 'nav-study-materials', title: '自学资料', subtitle: '/study-materials', icon: BookOpen, run: go('/study-materials') },
      { id: 'nav-blueprint', title: '蓝图组卷', subtitle: '/blueprint', icon: LayoutTemplate, run: go('/blueprint') },
      { id: 'nav-papers', title: '试卷管理', subtitle: '/papers', icon: Files, run: go('/papers') },
      { id: 'nav-settings', title: '设置', subtitle: '/settings', icon: Settings, run: go('/settings') },
    ]
  }, [navigate])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const key = String(e.key || '').toLowerCase()
      const ctrlOrMeta = e.ctrlKey || e.metaKey
      if (ctrlOrMeta && key === 'k') {
        e.preventDefault()
        if (isTypingTarget(e.target) && !open) {
          // Avoid hijacking common IME/search shortcuts when typing heavily. Still allow opening when already open.
          setOpen(true)
          return
        }
        setOpen((v) => !v)
      }
      if (key === 'escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="搜索功能或跳转…" />
      <CommandList>
        <CommandEmpty>无匹配结果</CommandEmpty>
        <CommandGroup heading="导航">
          {commands.map((c) => {
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
        <CommandGroup heading="提示">
          <CommandItem disabled>
            <span className="text-xs text-muted-foreground">快捷键：Ctrl/⌘ + K 打开面板</span>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}
