/**
 * Insert ``snippet`` at the current cursor position of an HTMLTextAreaElement
 * and return the resulting string. The caret is moved to the end of the
 * inserted snippet on the next animation frame so the focus remains usable.
 *
 * Pure helper – the React state setter is provided by the caller (so the
 * function works with any controlled textarea wrapper, not only the shadcn
 * ``Textarea`` component).
 */
export function insertAtTextareaCursor(
  textarea: HTMLTextAreaElement | null,
  snippet: string,
  setValue: (next: string) => void,
): void {
  const value = String(snippet || '')
  if (!value) return

  if (!textarea) {
    setValue(value)
    return
  }

  const start = textarea.selectionStart ?? textarea.value.length
  const end = textarea.selectionEnd ?? textarea.value.length
  const next = `${textarea.value.slice(0, start)}${value}${textarea.value.slice(end)}`
  setValue(next)

  requestAnimationFrame(() => {
    if (!textarea) return
    const cursor = start + value.length
    try {
      textarea.selectionStart = cursor
      textarea.selectionEnd = cursor
      textarea.focus()
    } catch {
      // Some browsers throw when the textarea is detached between frames –
      // no-op fallback so the LaTeX is still in the value.
    }
  })
}
