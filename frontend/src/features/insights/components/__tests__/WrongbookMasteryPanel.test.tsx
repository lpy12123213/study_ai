import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { WrongbookMasteryPanel } from '@/features/insights/components/WrongbookMasteryPanel'
import type { WrongbookInsights } from '@/api/insights'

describe('WrongbookMasteryPanel', () => {
  it('renders mastery distribution and weak point links', () => {
    const data: WrongbookInsights = {
      total: 3,
      mastery_distribution: [
        { bucket: '0-25', label: '0-25', count: 1 },
        { bucket: '26-50', label: '26-50', count: 0 },
        { bucket: '51-75', label: '51-75', count: 2 },
        { bucket: '76-100', label: '76-100', count: 0 },
      ],
      weak_points: [
        { knowledge_point: '导数', avg_mastery: 22, count: 2 },
        { knowledge_point: '函数', avg_mastery: 58, count: 1 },
      ],
    }

    render(
      <MemoryRouter>
        <WrongbookMasteryPanel data={data} />
      </MemoryRouter>
    )

    expect(screen.getByText('错题掌握度')).toBeInTheDocument()
    expect(screen.getByText('0-25')).toBeInTheDocument()
    expect(screen.getByText('导数')).toBeInTheDocument()
    expect(screen.getByText('22%')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /导数/ })).toHaveAttribute('href', expect.stringContaining('/wrongbook'))
  })

  it('renders an empty state without crashing', () => {
    const data: WrongbookInsights = {
      total: 0,
      mastery_distribution: [],
      weak_points: [],
    }

    render(
      <MemoryRouter>
        <WrongbookMasteryPanel data={data} />
      </MemoryRouter>
    )

    expect(screen.getByText('暂无错题掌握度数据')).toBeInTheDocument()
  })
})
