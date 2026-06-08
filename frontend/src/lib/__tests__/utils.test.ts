import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { formatDate } from '@/lib/utils'

describe('formatDate', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-06-08T00:30:00+08:00'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('uses local calendar days instead of rolling 24-hour windows', () => {
    expect(formatDate('2026-06-08T00:05:00+08:00')).toBe('今天')
    expect(formatDate('2026-06-07T23:50:00+08:00')).toBe('昨天')
    expect(formatDate('2026-06-06T12:00:00+08:00')).toBe('2天前')
  })

  it('returns an empty label for invalid dates', () => {
    expect(formatDate('not-a-date')).toBe('')
  })
})
