import { useEffect, useId, useState } from 'react'
import { Eye, Type } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Markdown } from '@/components/shared/Markdown'
import { cn } from '@/lib/utils'
import { FormulaToolbar } from './FormulaToolbar'
import { useFormulaEditor, type FormulaEditorMode, type FormulaSubject } from './useFormulaEditor'

export type FormulaEditorProps = {
  /** Controlled LaTeX value. */
  value: string
  onChange: (latex: string) => void
  /** Defaults to ``"text"`` so existing flows keep their current UX unless opted-in. */
  defaultMode?: FormulaEditorMode
  /** Subject filter controlling the visible toolbar groups. */
  defaultSubject?: FormulaSubject
  /** When false hides the visual/text toggle button (useful for read-only previews). */
  showModeToggle?: boolean
  /** When false hides the symbol toolbar entirely. */
  showToolbar?: boolean
  /** When true renders a live KaTeX preview pane below the editor. */
  showPreview?: boolean
  placeholder?: string
  className?: string
  /** Custom label for the visual ↔ text toggle button (i18n-friendly). */
  visualLabel?: string
  textLabel?: string
}

let _mathliveRegisterPromise: Promise<void> | null = null

/**
 * Lazily register MathLive's `<math-field>` web component. We only import the
 * library on demand so the main bundle does not pull in the ~100KB editor
 * unless a page actually mounts the visual mode.
 */
function ensureMathliveRegistered(): Promise<void> {
  if (typeof window === 'undefined') return Promise.resolve()
  if (_mathliveRegisterPromise) return _mathliveRegisterPromise
  _mathliveRegisterPromise = import('mathlive')
    .then(() => {
      // The dynamic import side-effect registers <math-field> globally.
    })
    .catch((error) => {
      // Surface the failure once; subsequent mounts will retry by clearing
      // the cached promise.
      _mathliveRegisterPromise = null
      console.warn('Failed to load MathLive', error)
    })
  return _mathliveRegisterPromise
}

/**
 * LaTeX-aware composer with a visual mathfield + text fallback toggle.
 *
 * - **Visual mode** loads MathLive on demand and binds its ``input`` event to
 *   the controlled value. Symbol toolbar buttons call ``executeCommand``.
 * - **Text mode** is the legacy textarea so existing flows keep working when
 *   MathLive cannot load (e.g. offline environments).
 * - A live KaTeX preview is available behind the ``showPreview`` flag using
 *   the shared ``Markdown`` renderer (already used elsewhere in the app), so
 *   styling stays consistent with the rest of the UI.
 */
export function FormulaEditor({
  value,
  onChange,
  defaultMode = 'text',
  defaultSubject = 'math',
  showModeToggle = true,
  showToolbar = true,
  showPreview = false,
  placeholder = '在此输入或粘贴 LaTeX，例如 \\frac{a}{b}',
  className,
  visualLabel = '可视化',
  textLabel = '纯文本',
}: FormulaEditorProps) {
  const editorId = useId()
  const editor = useFormulaEditor({
    initialLatex: value,
    initialMode: defaultMode,
    subject: defaultSubject,
    onLatexChange: onChange,
  })
  const [mathliveReady, setMathliveReady] = useState(false)

  // Sync external ``value`` updates back into the controller.
  useEffect(() => {
    if (value !== editor.latex) {
      editor.setLatex(value)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  // Lazy-load MathLive whenever the user switches to visual mode.
  useEffect(() => {
    if (editor.mode !== 'visual') return
    let cancelled = false
    ensureMathliveRegistered().then(() => {
      if (!cancelled) setMathliveReady(true)
    })
    return () => {
      cancelled = true
    }
  }, [editor.mode])

  // Bind <math-field> input → controller. We attach the listener manually so
  // we don't depend on any non-standard React typings.
  useEffect(() => {
    if (editor.mode !== 'visual' || !mathliveReady) return
    const node = editor.mathfieldRef.current
    if (!node) return
    const handler = () => {
      const next = (node as unknown as { value: string }).value || ''
      if (next !== editor.latex) {
        editor.setLatex(next)
      }
    }
    node.addEventListener('input', handler)
    // Initial sync so a non-empty external value propagates to the field.
    try {
      ;(node as unknown as { value: string }).value = editor.latex
    } catch {
      // Ignore – the field may not be ready on this tick.
    }
    return () => node.removeEventListener('input', handler)
  }, [editor.mode, mathliveReady, editor.latex, editor.mathfieldRef, editor])

  const previewMarkdown = editor.latex.trim() ? `$$${editor.latex}$$` : ''

  return (
    <div className={cn('aurora-formula-editor rounded-md border border-border bg-background', className)}>
      <div className="aurora-formula-editor-head flex items-center justify-between gap-2 border-b border-border bg-muted/40 px-2 py-1">
        <span className="text-xs text-muted-foreground" id={`${editorId}-label`}>
          公式编辑
        </span>
        {showModeToggle && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="aurora-formula-mode-toggle h-7 gap-1 px-2 text-xs"
            onClick={editor.toggleMode}
            aria-pressed={editor.mode === 'visual'}
            title={`切换到${editor.mode === 'visual' ? textLabel : visualLabel}`}
          >
            {editor.mode === 'visual' ? <Type className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            <span>{editor.mode === 'visual' ? textLabel : visualLabel}</span>
          </Button>
        )}
      </div>

      <div className="aurora-formula-editor-body space-y-2 p-2">
        {editor.mode === 'visual' ? (
          mathliveReady ? (
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (() => {
              const ref = (node: HTMLElement | null) => {
                editor.mathfieldRef.current = node
              }
              const props: Record<string, unknown> = {
                ref,
                placeholder,
                style: {
                  display: 'block',
                  minHeight: '2.5rem',
                  padding: '0.5rem',
                  fontSize: '1rem',
                  outline: 'none',
                },
                'aria-labelledby': `${editorId}-label`,
                className: 'aurora-formula-mathfield',
              }
              return <math-field {...(props as any)} />
            })()
          ) : (
            <div className="aurora-formula-loading rounded border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
              正在加载公式编辑器…
            </div>
          )
        ) : (
          <textarea
            ref={editor.textareaRef}
            value={editor.latex}
            onChange={(event) => editor.setLatex(event.target.value)}
            placeholder={placeholder}
            className="aurora-formula-textarea block min-h-[80px] w-full resize-y rounded border border-input bg-background px-3 py-2 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            aria-labelledby={`${editorId}-label`}
            spellCheck={false}
          />
        )}

        {showToolbar && (
          <FormulaToolbar
            subject={editor.subject}
            onSubjectChange={editor.setSubject}
            onInsert={editor.insertLatex}
          />
        )}

        {showPreview && (
          <div className="aurora-formula-preview rounded border border-dashed border-border bg-muted/30 p-2">
            <div className="mb-1 text-[11px] uppercase tracking-wide text-muted-foreground">实时预览</div>
            {previewMarkdown ? (
              <Markdown markdown={previewMarkdown} />
            ) : (
              <div className="text-sm text-muted-foreground">输入或点击符号即可看到预览</div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
