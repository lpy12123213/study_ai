import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { FormulaEditor } from './FormulaEditor'
import type { FormulaSubject } from './useFormulaEditor'

export type FormulaInsertDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Initial LaTeX value; defaults to empty so each open starts fresh. */
  initialLatex?: string
  /** Subject filter passed to the toolbar. */
  defaultSubject?: FormulaSubject
  /**
   * Called when the user confirms with a non-empty LaTeX string. The argument
   * is *not* wrapped in `\(...\)` / `$$...$$` – callers wrap as needed for
   * inline vs. display math (chat composer wraps inline; canvas / lesson
   * plan editors typically use display).
   */
  onInsert: (latex: string) => void
  /** Optional override for the dialog title. */
  title?: string
  /** Optional override for the description shown under the title. */
  description?: string
}

/**
 * Reusable modal that hosts {@link FormulaEditor} for "insert formula" flows.
 *
 * Pages that want to keep their existing textarea (e.g. Chat composer with its
 * Enter-to-send behaviour) can mount a small "Σ" button that opens this
 * dialog and inserts the resulting LaTeX into the active text input via their
 * own handler. This keeps the editor available everywhere without rewriting
 * every textarea.
 */
export function FormulaInsertDialog({
  open,
  onOpenChange,
  initialLatex = '',
  defaultSubject = 'math',
  onInsert,
  title = '插入公式',
  description = '可视化编辑或粘贴 LaTeX，点击“插入”将公式追加到光标位置。',
}: FormulaInsertDialogProps) {
  const [latex, setLatex] = useState(initialLatex)

  // Reset the editor every time the dialog is re-opened so previous edits do
  // not leak into a new flow.
  useEffect(() => {
    if (open) {
      setLatex(initialLatex)
    }
  }, [open, initialLatex])

  const handleInsert = () => {
    const cleaned = latex.trim()
    if (!cleaned) {
      onOpenChange(false)
      return
    }
    onInsert(cleaned)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="aurora-formula-dialog sm:max-w-[640px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <FormulaEditor
          value={latex}
          onChange={setLatex}
          defaultMode="visual"
          defaultSubject={defaultSubject}
          showPreview
          showToolbar
        />

        <DialogFooter>
          <Button type="button" className="aurora-shared-secondary-action" variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button type="button" className="aurora-shared-primary-action" onClick={handleInsert} disabled={!latex.trim()}>
            插入
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
