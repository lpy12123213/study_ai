import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MissionComposer } from '@/pages/aiGenerate/MissionComposer'

describe('MissionComposer', () => {
  it('reveals advanced controls on demand', async () => {
    const user = userEvent.setup()

    render(
      <MissionComposer
        missionText="为高一数学生成 5 道函数单调性中等难度题。"
        subject="高中数学"
        count="5"
        difficulty="中等"
        questionType=""
        useStudyArchive
        subjects={[
          { id: 1, code: '高中数学', name: '高中数学' },
          { id: 2, code: '初中数学', name: '初中数学' },
        ]}
        isGenerating={false}
        onMissionTextChange={vi.fn()}
        onSubjectChange={vi.fn()}
        onCountChange={vi.fn()}
        onDifficultyChange={vi.fn()}
        onQuestionTypeChange={vi.fn()}
        onUseStudyArchiveChange={vi.fn()}
        onGenerate={vi.fn()}
      />
    )

    expect(screen.queryByLabelText('学科')).not.toBeInTheDocument()
    expect(screen.getByText('LaTeX 公式规范')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '高级控制' }))

    expect(screen.getByLabelText('学科')).toBeInTheDocument()
    expect(screen.getByLabelText('题量')).toBeInTheDocument()
    expect(screen.getByLabelText('题型')).toBeInTheDocument()
  })
})
