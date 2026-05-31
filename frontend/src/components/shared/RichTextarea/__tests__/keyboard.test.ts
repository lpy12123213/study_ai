import { describe, expect, it } from 'vitest'

import { shouldSubmitRichTextareaEvent } from '../keyboard'

describe('RichTextarea keyboard guard', () => {
  it('submits plain Enter when submit-on-enter is enabled', () => {
    expect(shouldSubmitRichTextareaEvent({ key: 'Enter', shiftKey: false }, { submitOnEnter: true })).toBe(true)
  })

  it('keeps Shift+Enter available for new lines', () => {
    expect(shouldSubmitRichTextareaEvent({ key: 'Enter', shiftKey: true }, { submitOnEnter: true })).toBe(false)
  })

  it('does not submit while a browser IME composition is active', () => {
    expect(
      shouldSubmitRichTextareaEvent(
        { key: 'Enter', shiftKey: false, nativeEvent: { isComposing: true } },
        { submitOnEnter: true },
      ),
    ).toBe(false)
  })

  it('does not submit legacy IME keyCode 229 events', () => {
    expect(
      shouldSubmitRichTextareaEvent(
        { key: 'Enter', shiftKey: false, nativeEvent: { keyCode: 229 } },
        { submitOnEnter: true },
      ),
    ).toBe(false)
  })

  it('does not submit while the ProseMirror view is composing', () => {
    expect(
      shouldSubmitRichTextareaEvent({ key: 'Enter', shiftKey: false }, { submitOnEnter: true, viewComposing: true }),
    ).toBe(false)
  })

  it('can disable Enter-to-submit entirely', () => {
    expect(shouldSubmitRichTextareaEvent({ key: 'Enter', shiftKey: false }, { submitOnEnter: false })).toBe(false)
  })
})
