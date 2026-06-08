import { useCallback, useEffect, useRef, useState } from 'react'
import { Markdown } from '@tiptap/markdown'
import { Mathematics } from '@tiptap/extension-mathematics'
import { useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'

import type { FormulaSubject } from '@/components/shared/FormulaEditor'
import { editorMarkdownToStorageMarkdown, storageMarkdownToEditorMarkdown } from './extensions/markdownIO'

export type RichTextareaMathSelection = {
  latex: string
  pos: number
  kind: 'inline' | 'block'
}

export type UseRichTextareaOptions = {
  value: string
  onChange: (value: string) => void
  subject?: FormulaSubject
  disabled?: boolean
  debounceMs?: number
  editorClassName?: string
  ariaLabel?: string
  spellCheck?: boolean
}

export type RichTextareaController = {
  editor: Editor | null
  mathSelection: RichTextareaMathSelection | null
  openInsertDialog: () => void
  openMathDialog: boolean
  setOpenMathDialog: (open: boolean) => void
  activeLatex: string
  insertOrUpdateMath: (latex: string) => void
  subject: FormulaSubject
}

function nodeLatex(node: ProseMirrorNode): string {
  return typeof node.attrs?.latex === 'string' ? node.attrs.latex : ''
}

function isEditorDestroyed(editor: Editor): boolean {
  return Boolean((editor as Editor & { isDestroyed?: boolean }).isDestroyed)
}

function isUsableEditor(editor: Editor | null): editor is Editor {
  return Boolean(editor && !isEditorDestroyed(editor))
}

export function useRichTextarea({
  value,
  onChange,
  subject = 'math',
  disabled = false,
  debounceMs = 150,
  editorClassName,
  ariaLabel,
  spellCheck,
}: UseRichTextareaOptions): RichTextareaController {
  const [mathSelection, setMathSelection] = useState<RichTextareaMathSelection | null>(null)
  const [openMathDialog, setOpenMathDialog] = useState(false)
  const lastSerializedFromEditorRef = useRef(value)
  const changeTimerRef = useRef<number | null>(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  const clearChangeTimer = useCallback(() => {
    if (changeTimerRef.current == null) return
    window.clearTimeout(changeTimerRef.current)
    changeTimerRef.current = null
  }, [])

  const editor = useEditor(
    {
      editable: !disabled,
      extensions: [
        StarterKit,
        Mathematics.configure({
          katexOptions: { throwOnError: false },
          inlineOptions: {
            onClick: (node, pos) => {
              setMathSelection({ latex: nodeLatex(node), pos, kind: 'inline' })
              setOpenMathDialog(true)
            },
          },
          blockOptions: {
            onClick: (node, pos) => {
              setMathSelection({ latex: nodeLatex(node), pos, kind: 'block' })
              setOpenMathDialog(true)
            },
          },
        }),
        Markdown.configure({
          indentation: { style: 'space', size: 2 },
        }),
      ],
      content: storageMarkdownToEditorMarkdown(value),
      contentType: 'markdown',
      editorProps: {
        attributes: {
          class: editorClassName ?? '',
          role: 'textbox',
          'aria-multiline': 'true',
          ...(ariaLabel ? { 'aria-label': ariaLabel } : {}),
          ...(spellCheck == null ? {} : { spellcheck: spellCheck ? 'true' : 'false' }),
        },
      },
      onUpdate: ({ editor: activeEditor }) => {
        clearChangeTimer()
        const emitChange = () => {
          if (isEditorDestroyed(activeEditor)) return
          const next = editorMarkdownToStorageMarkdown(activeEditor.getMarkdown())
          lastSerializedFromEditorRef.current = next
          onChangeRef.current(next)
        }
        if (debounceMs <= 0) {
          emitChange()
          return
        }
        changeTimerRef.current = window.setTimeout(emitChange, debounceMs)
      },
    },
    [debounceMs, editorClassName, ariaLabel, spellCheck],
  )

  useEffect(() => {
    if (!isUsableEditor(editor)) return
    editor.setEditable(!disabled)
  }, [disabled, editor])

  useEffect(() => {
    if (!isUsableEditor(editor)) return
    if (value === lastSerializedFromEditorRef.current) return

    const current = editorMarkdownToStorageMarkdown(editor.getMarkdown())
    if (value === current) {
      lastSerializedFromEditorRef.current = value
      return
    }

    lastSerializedFromEditorRef.current = value
    editor.commands.setContent(storageMarkdownToEditorMarkdown(value), {
      contentType: 'markdown',
      emitUpdate: false,
    })
  }, [editor, value])

  useEffect(() => clearChangeTimer, [clearChangeTimer])

  const openInsertDialog = useCallback(() => {
    setMathSelection(null)
    setOpenMathDialog(true)
  }, [])

  const insertOrUpdateMath = useCallback(
    (latex: string) => {
      const cleaned = latex.trim()
      if (!cleaned || !isUsableEditor(editor)) return

      if (!mathSelection) {
        editor.chain().focus().insertInlineMath({ latex: cleaned }).run()
        return
      }

      if (mathSelection.kind === 'block') {
        editor.chain().focus().updateBlockMath({ latex: cleaned, pos: mathSelection.pos }).run()
      } else {
        editor.chain().focus().updateInlineMath({ latex: cleaned, pos: mathSelection.pos }).run()
      }
    },
    [editor, mathSelection],
  )

  return {
    editor,
    mathSelection,
    openInsertDialog,
    openMathDialog,
    setOpenMathDialog,
    activeLatex: mathSelection?.latex ?? '',
    insertOrUpdateMath,
    subject,
  }
}
