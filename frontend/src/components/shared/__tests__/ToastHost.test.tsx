import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastHost } from '@/components/shared/ToastHost'
import { useNotificationStore } from '@/stores/useNotificationStore'

describe('ToastHost', () => {
  beforeEach(() => {
    useNotificationStore.setState({ notifications: [], toasts: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
    useNotificationStore.setState({ notifications: [], toasts: [] })
  })

  it('does not restart existing toast timers when a new toast appears', () => {
    vi.useFakeTimers()

    render(
      <MemoryRouter>
        <ToastHost />
      </MemoryRouter>,
    )

    act(() => {
      useNotificationStore.getState().addToast({ id: 'old-toast', title: '旧通知', status: 'completed' })
    })
    expect(screen.getByText('旧通知')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(3000)
      useNotificationStore.getState().addToast({ id: 'new-toast', title: '新通知', status: 'completed' })
    })
    expect(screen.getByText('旧通知')).toBeInTheDocument()
    expect(screen.getByText('新通知')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(3000)
    })

    expect(screen.queryByText('旧通知')).not.toBeInTheDocument()
    expect(screen.getByText('新通知')).toBeInTheDocument()
  })
})
