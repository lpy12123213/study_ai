import { EditorContent } from '@tiptap/react'
import { Sigma } from 'lucide-react'
import type { CSSProperties } from 'react'

import { Button } from '@/components/ui/button'
import { FormulaInsertDialog, type FormulaSubject } from '@/components/shared/FormulaEditor'
import { cn } from '@/lib/utils'
import { shouldSubmitRichTextareaEvent } from './keyboard'
import { useRichTextarea } from './useRichTextarea'

export type RichTextareaProps = {
  value: string
  onChange: (value: string) => void
  onSubmit?: () => void
  placeholder?: string
  subject?: FormulaSubject
  disabled?: boolean
  submitOnEnter?: boolean
  minHeight?: number
  maxHeight?: number
  debounceMs?: number
  ariaLabel?: string
  spellCheck?: boolean
  style?: CSSProperties
  className?: string
  editorClassName?: string
}

export function RichTextarea({
  value,
  onChange,
  onSubmit,
  placeholder,
  subject = 'math',
  disabled = false,
  submitOnEnter = false,
  minHeight = 96,
  maxHeight = 260,
  debounceMs,
  ariaLabel,
  spellCheck,
  style,
  className,
  editorClassName,
}: RichTextareaProps) {
  const controller = useRichTextarea({
    value,
    onChange,
    subject,
    disabled,
    debounceMs,
    ariaLabel,
    spellCheck,
    editorClassName: cn(
      'rich-textarea-editor min-h-full px-3 py-2 text-sm leading-6 outline-none',
      'prose-p:m-0 prose-p:leading-6',
      editorClassName,
    ),
  })

  const empty = !value.trim()

  return (
    <div
      className={cn(
        'relative flex w-full rounded-md border border-input bg-card shadow-none',
        'focus-within:ring-1 focus-within:ring-ring',
        disabled && 'cursor-not-allowed opacity-50',
        className,
      )}
      data-rich-textarea-root
      style={{ minHeight, maxHeight, ...style }}
    >
      <div className="relative min-w-0 flex-1 overflow-y-auto" style={{ maxHeight }}>
        {placeholder && empty && (
          <div className="pointer-events-none absolute left-3 top-2 text-sm text-muted-foreground">
            {placeholder}
          </div>
        )}
        <EditorContent
          editor={controller.editor}
          onKeyDownCapture={(event) => {
            if (!onSubmit) return
            if (
              shouldSubmitRichTextareaEvent(event, {
                submitOnEnter,
                viewComposing: Boolean(controller.editor && !controller.editor.isDestroyed && controller.editor.view?.composing),
              })
            ) {
              event.preventDefault()
              onSubmit()
            }
          }}
        />
      </div>

      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="m-1 h-8 w-8 shrink-0 rounded-md"
        onClick={controller.openInsertDialog}
        disabled={disabled}
        title="插入公式"
        aria-label="插入公式"
      >
        <Sigma className="h-4 w-4" />
      </Button>

      <FormulaInsertDialog
        open={controller.openMathDialog}
        onOpenChange={controller.setOpenMathDialog}
        initialLatex={controller.activeLatex}
        defaultSubject={controller.subject}
        onInsert={controller.insertOrUpdateMath}
        title={controller.mathSelection ? '编辑公式' : '插入公式'}
        description="使用可视化公式编辑器，确认后写回富文本输入框。"
      />
    </div>
  )
}
