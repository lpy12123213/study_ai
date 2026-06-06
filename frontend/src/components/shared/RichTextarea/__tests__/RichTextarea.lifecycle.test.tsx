import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const editorState = vi.hoisted(() => ({
  editor: null as unknown,
}))

vi.mock('@tiptap/react', () => ({
  useEditor: vi.fn(() => editorState.editor),
  EditorContent: ({ editor }: { editor: unknown }) => (
    <div data-testid="editor" data-has-editor={String(Boolean(editor))} />
  ),
}))

vi.mock('@tiptap/markdown', () => ({
  Markdown: { configure: vi.fn(() => ({})) },
}))

vi.mock('@tiptap/extension-mathematics', () => ({
  Mathematics: { configure: vi.fn(() => ({})) },
}))

vi.mock('@tiptap/starter-kit', () => ({
  default: {},
}))

import { RichTextarea } from '../RichTextarea'

describe('RichTextarea lifecycle', () => {
  it('does not sync controlled content into a destroyed editor', () => {
    const setContent = vi.fn()
    editorState.editor = {
      isDestroyed: true,
      setEditable: vi.fn(),
      getMarkdown: vi.fn(() => ''),
      commands: { setContent },
    }

    const { rerender } = render(<RichTextarea value="" onChange={vi.fn()} />)

    expect(() => {
      rerender(<RichTextarea value="updated" onChange={vi.fn()} />)
    }).not.toThrow()
    expect(setContent).not.toHaveBeenCalled()
  })
})
