import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import type { FormulaSubject } from './useFormulaEditor'
import { visibleGroupsForSubject } from './symbols'

export type FormulaToolbarProps = {
  subject: FormulaSubject
  onInsert: (latex: string) => void
  onSubjectChange?: (subject: FormulaSubject) => void
  className?: string
  /** When true the toolbar is rendered as a single compact row (chat composer use case). */
  compact?: boolean
}

const SUBJECT_OPTIONS: Array<{ value: FormulaSubject; label: string }> = [
  { value: 'math', label: '数学' },
  { value: 'physics', label: '物理' },
  { value: 'chemistry', label: '化学' },
  { value: 'general', label: '通用' },
]

/**
 * Click-to-insert symbol panel for {@link FormulaEditor}.
 *
 * The toolbar is intentionally headless of MathLive – it just calls
 * ``onInsert(latex)`` so it works in both visual (mathfield) and text-mode
 * editors. Subject switcher is optional; pages that already pin a subject can
 * omit ``onSubjectChange``.
 */
export function FormulaToolbar({
  subject,
  onInsert,
  onSubjectChange,
  className,
  compact = false,
}: FormulaToolbarProps) {
  const groups = useMemo(() => visibleGroupsForSubject(subject), [subject])

  return (
    <div
      className={cn(
        'rounded-md border border-border bg-card text-card-foreground',
        compact ? 'p-1' : 'p-2',
        className,
      )}
      role="toolbar"
      aria-label="公式符号面板"
    >
      {onSubjectChange && (
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs text-muted-foreground">学科</span>
          <select
            className="h-7 rounded border border-input bg-background px-2 text-xs"
            value={subject}
            onChange={(event) => onSubjectChange(event.target.value as FormulaSubject)}
          >
            {SUBJECT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className={cn('grid gap-2', compact ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2')}>
        {groups.map((group) => (
          <div key={group.id} className="space-y-1">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {group.title}
            </div>
            <div className="flex flex-wrap gap-1">
              {group.symbols.map((symbol, idx) => (
                <button
                  key={`${group.id}-${idx}-${symbol.label}`}
                  type="button"
                  className={cn(
                    'inline-flex h-7 min-w-[28px] items-center justify-center rounded border border-border bg-background px-1.5 text-xs font-medium transition-colors hover:bg-muted',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                  )}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => onInsert(symbol.latex)}
                  aria-label={symbol.description || symbol.label}
                  title={symbol.description || symbol.label}
                >
                  {symbol.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
