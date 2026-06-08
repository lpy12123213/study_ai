import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CrawlDialog } from '@/features/generation/questionLibrary/CrawlDialog'

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ open, children }: { open: boolean; children: ReactNode }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: ReactNode }) => <div role="dialog">{children}</div>,
  DialogFooter: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode; value: string }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <button type="button">{children}</button>,
  SelectValue: () => <span>不限</span>,
}))

vi.mock('@/components/ui/switch', () => ({
  Switch: ({ checked, onCheckedChange }: { checked: boolean; onCheckedChange: (checked: boolean) => void }) => (
    <button type="button" aria-pressed={checked} onClick={() => onCheckedChange(!checked)} />
  ),
}))

describe('CrawlDialog', () => {
  afterEach(() => {
    cleanup()
  })

  it('uses default numeric values when numeric fields are cleared', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()

    render(<CrawlDialog open onOpenChange={vi.fn()} subject="数学" onSubmit={onSubmit} />)

    await user.type(screen.getByPlaceholderText('例如：函数 单调性'), '函数')
    await user.clear(screen.getByPlaceholderText('30'))
    await user.clear(screen.getByPlaceholderText('2'))
    await user.clear(screen.getByPlaceholderText('0'))
    await user.click(screen.getByRole('button', { name: /开始/ }))

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        limit: 30,
        max_pages: 2,
        min_quality_score: 0,
      }),
    )
  })

  it('resets local form state when reopened', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<CrawlDialog open onOpenChange={vi.fn()} subject="数学" onSubmit={vi.fn()} />)

    await user.type(screen.getByPlaceholderText('例如：函数 单调性'), '函数')
    await user.clear(screen.getByPlaceholderText('30'))
    await user.type(screen.getByPlaceholderText('30'), '80')

    rerender(<CrawlDialog open={false} onOpenChange={vi.fn()} subject="数学" onSubmit={vi.fn()} />)
    rerender(<CrawlDialog open onOpenChange={vi.fn()} subject="数学" onSubmit={vi.fn()} />)

    expect(screen.getByPlaceholderText('例如：函数 单调性')).toHaveValue('')
    expect(screen.getByPlaceholderText('30')).toHaveValue('30')
  })
})
