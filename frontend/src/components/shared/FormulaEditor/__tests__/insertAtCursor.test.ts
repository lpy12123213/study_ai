import { afterEach, describe, expect, it, vi } from 'vitest'

import { insertAtTextareaCursor } from '../insertAtCursor'

describe('insertAtTextareaCursor', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('appends the snippet when no textarea is provided', () => {
    const captured: string[] = []
    insertAtTextareaCursor(null, '\\(x^2\\)', (next) => captured.push(next))
    expect(captured).toEqual(['\\(x^2\\)'])
  })

  it('inserts at the current selection range', () => {
    const ta = document.createElement('textarea')
    ta.value = 'AB'
    ta.selectionStart = 1
    ta.selectionEnd = 1

    let captured = ''
    insertAtTextareaCursor(ta, 'X', (next) => {
      captured = next
    })
    expect(captured).toBe('AXB')
  })

  it('replaces the selection when a range is highlighted', () => {
    const ta = document.createElement('textarea')
    ta.value = 'aBBc'
    ta.selectionStart = 1
    ta.selectionEnd = 3

    let captured = ''
    insertAtTextareaCursor(ta, '?', (next) => {
      captured = next
    })
    expect(captured).toBe('a?c')
  })

  it('no-ops on empty snippet', () => {
    const ta = document.createElement('textarea')
    ta.value = 'hello'
    const setter = vi.fn()
    insertAtTextareaCursor(ta, '', setter)
    expect(setter).not.toHaveBeenCalled()
  })
})
