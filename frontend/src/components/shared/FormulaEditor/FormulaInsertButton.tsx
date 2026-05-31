import { useState, type ReactNode } from 'react'
import { Sigma } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { FormulaInsertDialog } from './FormulaInsertDialog'
import { insertAtTextareaCursor } from './insertAtCursor'
import type { FormulaSubject } from './useFormulaEditor'

export type FormulaInsertButtonProps = {
  /** Controlled value of the textarea the button targets. */
  value: string
  /** Setter that the parent uses to keep the textarea controlled. */
  onChange: (next: string) => void
  /** Ref to the textarea so insertion happens at the current caret. */
  textareaRef?: React.MutableRefObject<HTMLTextAreaElement | null> | React.RefObject<HTMLTextAreaElement>
  /**
   * How to format the inserted LaTeX. ``inline`` wraps it in ``\(...\)``,
   * ``display`` wraps it in ``$$...$$``, ``raw`` keeps the LaTeX as-is.
   * Defaults to ``inline`` since most chat / topic inputs render math inline.
   */
  wrap?: 'inline' | 'display' | 'raw'
  /** Subject filter forwarded to {@link FormulaToolbar}. */
  subject?: FormulaSubject
  /** Optional override for the rendered button content (defaults to a Σ icon). */
  children?: ReactNode
  /** When true the trigger renders as an icon-only square (chat composer use case). */
  iconOnly?: boolean
  className?: string
  /** Optional custom title for the dialog. */
  dialogTitle?: string
  disabled?: boolean
}

/**
 * Trigger + dialog combo that lets a textarea owner add a "Σ 公式" button
 * without rewriting their input element.
 *
 * Existing pages keep their textarea (and Enter-to-send / auto-grow logic);
 * this component only owns the dialog open state and forwards the LaTeX into
 * the controlled textarea via ``insertAtTextareaCursor``.
 */
export function FormulaInsertButton({
  value,
  onChange,
  textareaRef,
  wrap = 'inline',
  subject = 'math',
  children,
  iconOnly = false,
  className,
  dialogTitle,
  disabled,
}: FormulaInsertButtonProps) {
  const [open, setOpen] = useState(false)

  const handleInsert = (latex: string) => {
    const wrapped = wrap === 'display' ? `$$${latex}$$` : wrap === 'raw' ? latex : `\\(${latex}\\)`
    const target = textareaRef?.current ?? null
    insertAtTextareaCursor(target, wrapped, (next) => onChange(next ?? `${value}${wrapped}`))
  }

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size={iconOnly ? 'icon' : 'sm'}
        className={cn(iconOnly ? 'h-8 w-8 shrink-0' : 'h-8 gap-1 px-2', className)}
        onClick={() => setOpen(true)}
        aria-label="插入公式"
        title="插入公式"
        disabled={disabled}
      >
        <Sigma className={iconOnly ? 'h-4 w-4' : 'h-3.5 w-3.5'} />
        {!iconOnly && (children ?? <span className="text-xs">公式</span>)}
      </Button>
      <FormulaInsertDialog
        open={open}
        onOpenChange={setOpen}
        defaultSubject={subject}
        onInsert={handleInsert}
        title={dialogTitle}
      />
    </>
  )
}
