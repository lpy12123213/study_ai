import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PickQuestionsPanel } from '@/features/canvas/components/PickQuestionsPanel'
import type { PickedCanvasQuestion } from '@/api/canvas'

describe('PickQuestionsPanel', () => {
  it('renders picked questions and adds the selected question to the board', async () => {
    const user = userEvent.setup()
    const question: PickedCanvasQuestion = {
      success: true,
      questionId: '1001',
      title: '函数零点综合题',
      stemHtml: '<p>题干</p>',
      selectReason: '匹配当前要求',
    }
    const onPick = vi.fn().mockResolvedValue([question])
    const onAdd = vi.fn()

    render(<PickQuestionsPanel subject="高中数学" loading={false} onPick={onPick} onAdd={onAdd} />)

    await user.type(screen.getByPlaceholderText('例如：函数零点与导数综合，偏中难'), '函数零点')
    await user.click(screen.getByRole('button', { name: /搜索题目/ }))

    await waitFor(() => expect(screen.getByText('函数零点综合题')).toBeInTheDocument())
    expect(onPick).toHaveBeenCalledWith({ requirement: '函数零点', subject: '高中数学', count: 3 })

    await user.click(screen.getByText('函数零点综合题'))
    expect(onAdd).toHaveBeenCalledWith([question])
  })
})
