import type { ReactNode } from 'react'
import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import type {
  ContentLayout,
  DesignStylePresetMeta,
  SidebarPosition,
  SidebarStyle,
} from '@/stores/useAppearanceStore'

export function StyleOptionCard(props: {
  label: string
  description?: string
  selected: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button type="button" className="group block w-full text-left" onClick={props.onClick}>
      <div
        className={cn(
          'relative h-24 rounded-lg border bg-muted/30 p-3 transition-colors',
          props.selected ? 'border-primary ring-2 ring-primary/15' : 'border-border hover:border-primary/50',
        )}
      >
        {props.children}
        {props.selected && (
          <span className="absolute -right-2 -top-2 flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-none">
            <Check className="h-4 w-4" />
          </span>
        )}
      </div>
      <div className="mt-2 text-center text-sm font-medium">{props.label}</div>
      {props.description ? <div className="mt-1 text-center text-xs text-muted-foreground">{props.description}</div> : null}
    </button>
  )
}

export function DesignStylePreview({ preset }: { preset: DesignStylePresetMeta }) {
  return (
    <div
      className="h-full overflow-hidden rounded-md border"
      style={{ backgroundColor: preset.background, borderColor: preset.surface }}
    >
      <div className="flex h-full">
        <div className="w-1/3 border-r p-2" style={{ borderColor: preset.surface, backgroundColor: preset.surface }}>
          <div className="h-3 w-3 rounded-md" style={{ backgroundColor: preset.accent }} />
          <div className="mt-2 h-1.5 w-10 rounded" style={{ backgroundColor: preset.foreground, opacity: 0.7 }} />
          <div className="mt-1 h-1.5 w-7 rounded" style={{ backgroundColor: preset.foreground, opacity: 0.35 }} />
          <div className="mt-1 h-1.5 w-9 rounded" style={{ backgroundColor: preset.foreground, opacity: 0.25 }} />
        </div>
        <div className="flex-1 p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="h-2 w-20 rounded" style={{ backgroundColor: preset.foreground, opacity: 0.8 }} />
            <div className="h-5 w-10 rounded-md" style={{ backgroundColor: preset.accent }} />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <div className="h-9 rounded-md border" style={{ borderColor: preset.surface, backgroundColor: preset.surface }} />
            <div className="h-9 rounded-md border" style={{ borderColor: preset.surface, backgroundColor: preset.surface }} />
          </div>
        </div>
      </div>
    </div>
  )
}

export function ThemePreview({ mode }: { mode: 'system' | 'light' | 'dark' }) {
  const dark = mode === 'dark'
  const system = mode === 'system'
  return (
    <div className={cn('h-full rounded-md border overflow-hidden', dark ? 'bg-slate-950' : 'bg-white')}>
      <div className={cn('flex h-full', system && 'opacity-80')}>
        <div className={cn('w-1/3 p-2 space-y-1.5', dark ? 'bg-slate-900' : 'bg-slate-200')}>
          <div className={cn('h-3 w-3 rounded-full', dark ? 'bg-sky-400' : 'bg-white')} />
          <div className={cn('h-1.5 w-8 rounded', dark ? 'bg-sky-500/70' : 'bg-white')} />
          <div className={cn('h-1.5 w-10 rounded', dark ? 'bg-slate-500' : 'bg-slate-400')} />
          <div className={cn('h-1.5 w-7 rounded', dark ? 'bg-slate-500' : 'bg-slate-400')} />
        </div>
        <div className="flex-1 p-3">
          <div className={cn('ml-auto h-8 w-8 rounded-full', dark ? 'bg-blue-950' : 'bg-slate-100')} />
          <div className={cn('mt-2 h-10 rounded', dark ? 'bg-slate-800' : 'bg-slate-100')} />
        </div>
      </div>
    </div>
  )
}

export function SidebarPreview({ value }: { value: SidebarStyle }) {
  return (
    <div className="h-full rounded-md border bg-background p-2">
      <div
        className={cn(
          'h-full rounded-md',
          value === 'sidebar' && 'w-1/3 bg-primary/20',
          value === 'inset' && 'ml-1 w-1/3 border bg-primary/10',
          value === 'floating' && 'ml-2 w-1/4 rounded-lg border bg-primary/15 shadow-sm',
        )}
      >
        <div className="space-y-1.5 p-2">
          <div className="h-2 w-2 rounded-full bg-primary/70" />
          <div className="h-1.5 w-8 rounded bg-primary/50" />
          <div className="h-1.5 w-6 rounded bg-muted-foreground/40" />
          <div className="h-1.5 w-7 rounded bg-muted-foreground/40" />
        </div>
      </div>
    </div>
  )
}

export function LayoutPreview({ value }: { value: ContentLayout }) {
  const widthClass = value === 'full' ? 'w-full' : value === 'compact' ? 'w-1/2' : 'w-2/3'
  return (
    <div className="h-full rounded-md border bg-background p-2">
      <div className={cn('mx-auto h-full rounded-md bg-primary/15 p-2', widthClass)}>
        <div className="h-2 w-full rounded bg-primary/50" />
        <div className="mt-2 h-8 rounded bg-muted-foreground/25" />
        <div className="mt-2 flex gap-1">
          <div className="h-4 flex-1 rounded bg-muted-foreground/25" />
          <div className="h-4 flex-1 rounded bg-muted-foreground/25" />
        </div>
      </div>
    </div>
  )
}

export function PositionPreview({ value }: { value: SidebarPosition }) {
  return (
    <div className={cn('flex h-full rounded-md border bg-background', value === 'right' && 'flex-row-reverse')}>
      <div className="w-1/4 bg-primary/20 p-2">
        <div className="h-2 w-2 rounded-full bg-primary/70" />
        <div className="mt-2 h-1.5 w-8 rounded bg-primary/50" />
        <div className="mt-1 h-1.5 w-6 rounded bg-muted-foreground/40" />
      </div>
      <div className="flex-1 p-3">
        <div className="h-8 rounded bg-muted-foreground/25" />
        <div className="mt-2 h-3 rounded bg-muted-foreground/20" />
      </div>
    </div>
  )
}
