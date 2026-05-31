import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/**
 * Headless controller for {@link FormulaEditor}.
 *
 * Owns the LaTeX value plus a few visual toggles (visual vs. text mode, focus
 * tracking) so the rendering layer stays a thin React component. Keeping the
 * state here also lets call-sites mix the editor with their own form state
 * without re-implementing the toggle logic on every page.
 */
export type FormulaEditorMode = 'visual' | 'text'

export type FormulaSubject = 'math' | 'physics' | 'chemistry' | 'general'

export type UseFormulaEditorOptions = {
  /** Initial LaTeX string. Subsequent prop changes are not synced (use a key). */
  initialLatex?: string
  /** Initial editor mode. Defaults to "text" so existing flows are unchanged. */
  initialMode?: FormulaEditorMode
  /** Subject filter for the visual symbol panel. */
  subject?: FormulaSubject
  /** Called whenever the LaTeX value changes (visual or text mode). */
  onLatexChange?: (latex: string) => void
}

export type UseFormulaEditorResult = {
  latex: string
  setLatex: (next: string) => void
  mode: FormulaEditorMode
  setMode: (next: FormulaEditorMode) => void
  toggleMode: () => void
  subject: FormulaSubject
  setSubject: (next: FormulaSubject) => void
  /**
   * Insert a LaTeX snippet at the current cursor position. In text mode this
   * appends to the textarea content; in visual mode the wrapper component
   * uses the active mathfield's `executeCommand('insert', latex)` API.
   */
  insertLatex: (snippet: string) => void
  /** Imperatively focus the active editor (visual or text). */
  focus: () => void
  /** Imperative ref handle for the underlying mathfield element. */
  mathfieldRef: React.MutableRefObject<HTMLElement | null>
  /** Imperative ref handle for the fallback textarea element. */
  textareaRef: React.MutableRefObject<HTMLTextAreaElement | null>
}

/**
 * Hook controlling the LaTeX value + visual/text toggle for the editor.
 *
 * Note: MathLive itself is loaded lazily inside the component to keep the
 * initial bundle lean. The hook stays free of any MathLive imports so it can
 * also be unit-tested with happy-dom.
 */
export function useFormulaEditor({
  initialLatex = '',
  initialMode = 'text',
  subject = 'math',
  onLatexChange,
}: UseFormulaEditorOptions = {}): UseFormulaEditorResult {
  const [latex, setLatexState] = useState(initialLatex)
  const [mode, setMode] = useState<FormulaEditorMode>(initialMode)
  const [subjectState, setSubject] = useState<FormulaSubject>(subject)

  const mathfieldRef = useRef<HTMLElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  // Stable change-callback ref so consumers can pass inline arrow functions
  // without forcing the editor to re-render on every parent render.
  const changeCallbackRef = useRef(onLatexChange)
  useEffect(() => {
    changeCallbackRef.current = onLatexChange
  }, [onLatexChange])

  const setLatex = useCallback((next: string) => {
    setLatexState((prev) => {
      if (prev === next) return prev
      return next
    })
    changeCallbackRef.current?.(next)
  }, [])

  const toggleMode = useCallback(() => {
    setMode((prev) => (prev === 'visual' ? 'text' : 'visual'))
  }, [])

  const insertLatex = useCallback(
    (snippet: string) => {
      const value = String(snippet || '')
      if (!value) return
      if (mode === 'visual' && mathfieldRef.current && 'executeCommand' in mathfieldRef.current) {
        try {
          ;(mathfieldRef.current as unknown as { executeCommand: (cmd: string, arg?: string) => void }).executeCommand(
            'insert',
            value,
          )
        } catch {
          // Mathfield not ready – fall through to value append.
          setLatex(`${latex}${value}`)
        }
        return
      }

      const ta = textareaRef.current
      if (ta) {
        const start = ta.selectionStart ?? ta.value.length
        const end = ta.selectionEnd ?? ta.value.length
        const next = `${ta.value.slice(0, start)}${value}${ta.value.slice(end)}`
        setLatex(next)
        // Restore caret right after the inserted snippet on next tick.
        requestAnimationFrame(() => {
          if (!textareaRef.current) return
          const cursor = start + value.length
          textareaRef.current.selectionStart = cursor
          textareaRef.current.selectionEnd = cursor
          textareaRef.current.focus()
        })
        return
      }

      setLatex(`${latex}${value}`)
    },
    [latex, mode, setLatex],
  )

  const focus = useCallback(() => {
    if (mode === 'visual' && mathfieldRef.current && 'focus' in mathfieldRef.current) {
      try {
        ;(mathfieldRef.current as unknown as { focus: () => void }).focus()
        return
      } catch {
        // Fall through to textarea focus below.
      }
    }
    textareaRef.current?.focus()
  }, [mode])

  return useMemo(
    () => ({
      latex,
      setLatex,
      mode,
      setMode,
      toggleMode,
      subject: subjectState,
      setSubject,
      insertLatex,
      focus,
      mathfieldRef,
      textareaRef,
    }),
    [latex, setLatex, mode, toggleMode, subjectState, insertLatex, focus],
  )
}
