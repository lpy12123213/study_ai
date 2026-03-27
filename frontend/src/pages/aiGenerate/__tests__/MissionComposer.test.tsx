import { fireEvent, render, screen } from '@testing-library/react'
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
        useReferenceQuestions
        referenceSource="any"
        referenceYearRange="all"
        mode="standard"
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
        onUseReferenceQuestionsChange={vi.fn()}
        onReferenceSourceChange={vi.fn()}
        onReferenceYearRangeChange={vi.fn()}
        onModeChange={vi.fn()}
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

  it('resizes the mission textarea with the drag handle', () => {
    render(
      <MissionComposer
        missionText="为高一数学生成 5 道函数单调性中等难度题。"
        subject="高中数学"
        count="5"
        difficulty="中等"
        questionType=""
        useStudyArchive
        useReferenceQuestions
        referenceSource="any"
        referenceYearRange="all"
        mode="standard"
        subjects={[{ id: 1, code: '高中数学', name: '高中数学' }]}
        isGenerating={false}
        onMissionTextChange={vi.fn()}
        onSubjectChange={vi.fn()}
        onCountChange={vi.fn()}
        onDifficultyChange={vi.fn()}
        onQuestionTypeChange={vi.fn()}
        onUseStudyArchiveChange={vi.fn()}
        onUseReferenceQuestionsChange={vi.fn()}
        onReferenceSourceChange={vi.fn()}
        onReferenceYearRangeChange={vi.fn()}
        onModeChange={vi.fn()}
        onGenerate={vi.fn()}
      />
    )

    const textareas = screen.getAllByRole('textbox', { name: '出题任务描述' })
    const handles = screen.getAllByRole('button', { name: '调整任务输入框高度' })
    const textarea = textareas[textareas.length - 1] as HTMLTextAreaElement
    const handle = handles[handles.length - 1]

    fireEvent.mouseDown(handle, { clientY: 200 })
    fireEvent.mouseMove(document, { clientY: 280 })
    fireEvent.mouseUp(document)

    expect(textarea.style.height).toBe('204px')
  })

  it('clamps mission textarea height at max value while dragging', () => {
    render(
      <MissionComposer
        missionText="为高一数学生成 5 道函数单调性中等难度题。"
        subject="高中数学"
        count="5"
        difficulty="中等"
        questionType=""
        useStudyArchive
        useReferenceQuestions
        referenceSource="any"
        referenceYearRange="all"
        mode="standard"
        subjects={[{ id: 1, code: '高中数学', name: '高中数学' }]}
        isGenerating={false}
        onMissionTextChange={vi.fn()}
        onSubjectChange={vi.fn()}
        onCountChange={vi.fn()}
        onDifficultyChange={vi.fn()}
        onQuestionTypeChange={vi.fn()}
        onUseStudyArchiveChange={vi.fn()}
        onUseReferenceQuestionsChange={vi.fn()}
        onReferenceSourceChange={vi.fn()}
        onReferenceYearRangeChange={vi.fn()}
        onModeChange={vi.fn()}
        onGenerate={vi.fn()}
      />
    )

    const textareas = screen.getAllByRole('textbox', { name: '出题任务描述' })
    const handles = screen.getAllByRole('button', { name: '调整任务输入框高度' })
    const textarea = textareas[textareas.length - 1] as HTMLTextAreaElement
    const handle = handles[handles.length - 1]

    fireEvent.mouseDown(handle, { clientY: 200 })
    fireEvent.mouseMove(document, { clientY: 800 })
    fireEvent.mouseUp(document)

    expect(textarea.style.height).toBe('320px')
  })

  it('adjusts mission textarea height using click controls', () => {
    render(
      <MissionComposer
        missionText="为高一数学生成 5 道函数单调性中等难度题。"
        subject="高中数学"
        count="5"
        difficulty="中等"
        questionType=""
        useStudyArchive
        useReferenceQuestions
        referenceSource="any"
        referenceYearRange="all"
        mode="standard"
        subjects={[{ id: 1, code: '高中数学', name: '高中数学' }]}
        isGenerating={false}
        onMissionTextChange={vi.fn()}
        onSubjectChange={vi.fn()}
        onCountChange={vi.fn()}
        onDifficultyChange={vi.fn()}
        onQuestionTypeChange={vi.fn()}
        onUseStudyArchiveChange={vi.fn()}
        onUseReferenceQuestionsChange={vi.fn()}
        onReferenceSourceChange={vi.fn()}
        onReferenceYearRangeChange={vi.fn()}
        onModeChange={vi.fn()}
        onGenerate={vi.fn()}
      />
    )

    const textareas = screen.getAllByRole('textbox', { name: '出题任务描述' })
    const textarea = textareas[textareas.length - 1] as HTMLTextAreaElement
    const increaseButtons = screen.getAllByRole('button', { name: '增大任务输入框高度' })
    const decreaseButtons = screen.getAllByRole('button', { name: '减小任务输入框高度' })
    const increase = increaseButtons[increaseButtons.length - 1]!
    const decrease = decreaseButtons[decreaseButtons.length - 1]!

    expect(textarea.style.height).toBe('124px')
    fireEvent.click(increase)
    expect(textarea.style.height).toBe('148px')
    fireEvent.click(decrease)
    expect(textarea.style.height).toBe('124px')
  })
})
