import { useCallback, useState } from 'react'
import { parseTagsInput } from './utils'

type UseTagEditorOptions<TItem> = {
  /** Stable identity for the row currently being edited (paper id, archive id, ...). */
  getItemId: (item: TItem) => string
  /** Initial CSV value to populate when the dialog opens. */
  getInitialValue: (item: TItem) => string
  /**
   * Called with a parsed array (already trimmed, deduped, ≤20). Persist via your
   * mutation hook here.
   */
  onSave: (item: TItem, tags: string[]) => void
}

type UseTagEditorResult<TItem> = {
  /** Currently editing item, or null when the dialog is closed. */
  editing: TItem | null
  /** CSV-formatted text bound to the dialog input. */
  value: string
  setValue: (value: string) => void
  open: (item: TItem) => void
  close: () => void
  save: () => void
  /** True iff the editor dialog should be visible. */
  isOpen: boolean
}

/**
 * Headless controller for the shared {@link TagEditDialog}.
 *
 * Centralizes the open/save/close lifecycle so individual master-detail pages
 * only need to call ``open(item)`` from their UI; persistence happens through
 * the ``onSave`` callback supplied by the caller.
 */
export function useTagEditor<TItem>({
  getItemId: _getItemId,
  getInitialValue,
  onSave,
}: UseTagEditorOptions<TItem>): UseTagEditorResult<TItem> {
  const [editing, setEditing] = useState<TItem | null>(null)
  const [value, setValue] = useState<string>('')

  const open = useCallback(
    (item: TItem) => {
      setEditing(item)
      setValue(getInitialValue(item))
    },
    [getInitialValue],
  )

  const close = useCallback(() => {
    setEditing(null)
    setValue('')
  }, [])

  const save = useCallback(() => {
    if (!editing) return
    const tags = parseTagsInput(value)
    onSave(editing, tags)
    setEditing(null)
    setValue('')
  }, [editing, value, onSave])

  return {
    editing,
    value,
    setValue,
    open,
    close,
    save,
    isOpen: editing !== null,
  }
}
