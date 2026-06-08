import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Markdown } from '@/components/shared/Markdown'

vi.mock('@/api/client', () => ({
  downloadObjectUrl: vi.fn(),
  resolveApiResourceUrl: vi.fn((url: string) => url),
}))

describe('Markdown', () => {
  it('renders backslash math delimiters used by generated content', () => {
    const { container } = render(
      <Markdown content={'行内 \\(x^2+1\\)，块公式：\\[\\frac{1}{2}\\]'} />
    )

    expect(container.querySelector('.katex')).not.toBeNull()
    expect(container.querySelector('.katex-display')).not.toBeNull()
    expect(container.textContent || '').not.toContain('\\(')
    expect(container.textContent || '').not.toContain('\\[')
  })
})
