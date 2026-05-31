import { describe, expect, it } from 'vitest'

import { isImeCompositionKeyboardEvent, shouldSubmitOnEnter } from '../keyboard'

describe('keyboard submit helpers', () => {
  it('does not submit Enter while an IME composition is active', () => {
    expect(
      shouldSubmitOnEnter({
        key: 'Enter',
        shiftKey: false,
        nativeEvent: { isComposing: true },
      }),
    ).toBe(false)
  })

  it('does not submit Enter for legacy IME keyCode 229 events', () => {
    expect(
      shouldSubmitOnEnter({
        key: 'Enter',
        shiftKey: false,
        nativeEvent: { keyCode: 229 },
      }),
    ).toBe(false)
  })

  it('submits plain Enter and preserves Shift+Enter as newline', () => {
    expect(shouldSubmitOnEnter({ key: 'Enter', shiftKey: false })).toBe(true)
    expect(shouldSubmitOnEnter({ key: 'Enter', shiftKey: true })).toBe(false)
  })

  it('detects IME composition on native and React-style keyboard events', () => {
    expect(isImeCompositionKeyboardEvent({ key: 'Enter', isComposing: true })).toBe(true)
    expect(isImeCompositionKeyboardEvent({ key: 'Enter', nativeEvent: { keyCode: 229 } })).toBe(true)
    expect(isImeCompositionKeyboardEvent({ key: 'Enter' })).toBe(false)
  })
})
