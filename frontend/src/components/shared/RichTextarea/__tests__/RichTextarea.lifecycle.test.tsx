import { render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

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
import { useEditor } from '@tiptap/react'

describe('RichTextarea lifecycle', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

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

  it('updates disabled state without changing editor creation dependencies', () => {
    const setEditable = vi.fn()
    editorState.editor = {
      isDestroyed: false,
      setEditable,
      getMarkdown: vi.fn(() => ''),
      commands: { setContent: vi.fn() },
    }
    const useEditorMock = vi.mocked(useEditor)

    const { rerender } = render(<RichTextarea value="" onChange={vi.fn()} disabled={false} />)
    const firstDeps = useEditorMock.mock.calls[useEditorMock.mock.calls.length - 1]?.[1]

    rerender(<RichTextarea value="" onChange={vi.fn()} disabled />)
    const secondDeps = useEditorMock.mock.calls[useEditorMock.mock.calls.length - 1]?.[1]

    expect(secondDeps).toEqual(firstDeps)
    expect(setEditable).toHaveBeenLastCalledWith(false)
  })
})
