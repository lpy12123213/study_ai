import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useNotificationStore } from '@/stores/useNotificationStore'

describe('useNotificationStore', () => {
  beforeEach(() => {
    useNotificationStore.setState({ notifications: [], toasts: [] })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('assigns distinct ids to multiple implicit toasts created in the same millisecond', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_800_000_000_000)

    useNotificationStore.getState().addToast({ title: '第一条' })
    useNotificationStore.getState().addToast({ title: '第二条' })

    const toasts = useNotificationStore.getState().toasts
    expect(toasts).toHaveLength(2)
    expect(new Set(toasts.map((toast) => toast.id)).size).toBe(2)
  })
})
