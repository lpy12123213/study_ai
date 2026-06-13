import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { WorkspaceSplitLayout } from '@/components/layout/WorkspaceSplitLayout'

vi.mock('@/features/workspace/useMasterList', () => ({
  useMasterList: () => ({
    data: [{ id: '1', title: '教案 A', subtitle: '数学 · 高一', to: '/lesson-plans/1' }],
    isLoading: false,
  }),
}))

function renderAt(initialEntry: string) {
  const router = createMemoryRouter(
    [
      {
        path: '/lesson-plans',
        element: <WorkspaceSplitLayout kind="lesson-plans" />,
        children: [
          { index: true, element: <div>列表概览</div> },
          { path: ':lessonPlanId', element: <div>详情内容</div> },
        ],
      },
    ],
    { initialEntries: [initialEntry] },
  )
  return render(<RouterProvider router={router} />)
}

describe('WorkspaceSplitLayout', () => {
  it('shows the master list full-width on mobile for the index route', () => {
    const { container } = renderAt('/lesson-plans')

    expect(screen.getByText('教案 A')).toBeInTheDocument()
    expect(screen.getByText('列表概览')).toBeInTheDocument()

    const aside = container.querySelector('aside')
    const main = container.querySelector('main')
    expect(aside?.className).toContain('w-full')
    expect(aside?.className).not.toContain('hidden')
    expect(main?.className).toContain('hidden')
    expect(main?.className).toContain('lg:block')
  })

  it('hides the master list on mobile for the detail route', () => {
    const { container } = renderAt('/lesson-plans/1')

    expect(screen.getByText('详情内容')).toBeInTheDocument()

    const aside = container.querySelector('aside')
    const main = container.querySelector('main')
    expect(aside?.className).toContain('hidden')
    expect(main?.className).toContain('block')
    expect(main?.className).not.toMatch(/(^| )hidden( |$)/)
  })
})
