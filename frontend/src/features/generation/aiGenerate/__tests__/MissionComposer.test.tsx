import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { MissionComposer } from '@/features/generation/aiGenerate/MissionComposer'

describe('MissionComposer', () => {
  beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', { configurable: true, value: () => false })
    Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', { configurable: true, value: () => undefined })
    Object.defineProperty(HTMLElement.prototype, 'releasePointerCapture', { configurable: true, value: () => undefined })
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: () => undefined })
  })

  afterEach(() => cleanup())

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
        practiceGoal="structural_intuition"
        intuitionKinds={['prediction', 'representation', 'invariant']}
        packetSize={3}
        feedbackMode="guided"
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
        onPracticeGoalChange={vi.fn()}
        onIntuitionKindsChange={vi.fn()}
        onPacketSizeChange={vi.fn()}
        onFeedbackModeChange={vi.fn()}
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
        practiceGoal="structural_intuition"
        intuitionKinds={['prediction', 'representation', 'invariant']}
        packetSize={3}
        feedbackMode="guided"
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
        onPracticeGoalChange={vi.fn()}
        onIntuitionKindsChange={vi.fn()}
        onPacketSizeChange={vi.fn()}
        onFeedbackModeChange={vi.fn()}
        onModeChange={vi.fn()}
        onGenerate={vi.fn()}
      />
    )

    const textareas = screen.getAllByRole('textbox', { name: '出题任务描述' })
    const handles = screen.getAllByRole('button', { name: '调整任务输入框高度' })
    const editorRoot = textareas[textareas.length - 1]!.closest('[data-rich-textarea-root]') as HTMLElement
    const handle = handles[handles.length - 1]

    fireEvent.mouseDown(handle, { clientY: 200 })
    fireEvent.mouseMove(document, { clientY: 280 })
    fireEvent.mouseUp(document)

    expect(editorRoot.style.height).toBe('204px')
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
        practiceGoal="structural_intuition"
        intuitionKinds={['prediction', 'representation', 'invariant']}
        packetSize={3}
        feedbackMode="guided"
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
        onPracticeGoalChange={vi.fn()}
        onIntuitionKindsChange={vi.fn()}
        onPacketSizeChange={vi.fn()}
        onFeedbackModeChange={vi.fn()}
        onModeChange={vi.fn()}
        onGenerate={vi.fn()}
      />
    )

    const textareas = screen.getAllByRole('textbox', { name: '出题任务描述' })
    const handles = screen.getAllByRole('button', { name: '调整任务输入框高度' })
    const editorRoot = textareas[textareas.length - 1]!.closest('[data-rich-textarea-root]') as HTMLElement
    const handle = handles[handles.length - 1]

    fireEvent.mouseDown(handle, { clientY: 200 })
    fireEvent.mouseMove(document, { clientY: 800 })
    fireEvent.mouseUp(document)

    expect(editorRoot.style.height).toBe('320px')
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
        practiceGoal="structural_intuition"
        intuitionKinds={['prediction', 'representation', 'invariant']}
        packetSize={3}
        feedbackMode="guided"
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
        onPracticeGoalChange={vi.fn()}
        onIntuitionKindsChange={vi.fn()}
        onPacketSizeChange={vi.fn()}
        onFeedbackModeChange={vi.fn()}
        onModeChange={vi.fn()}
        onGenerate={vi.fn()}
      />
    )

    const textareas = screen.getAllByRole('textbox', { name: '出题任务描述' })
    const editorRoot = textareas[textareas.length - 1]!.closest('[data-rich-textarea-root]') as HTMLElement
    const increaseButtons = screen.getAllByRole('button', { name: '增大任务输入框高度' })
    const decreaseButtons = screen.getAllByRole('button', { name: '减小任务输入框高度' })
    const increase = increaseButtons[increaseButtons.length - 1]!
    const decrease = decreaseButtons[decreaseButtons.length - 1]!

    expect(editorRoot.style.height).toBe('124px')
    fireEvent.click(increase)
    expect(editorRoot.style.height).toBe('148px')
    fireEvent.click(decrease)
    expect(editorRoot.style.height).toBe('124px')
  })

  it('exposes intuition practice controls on the original composer', async () => {
    const user = userEvent.setup()
    const onPracticeGoalChange = vi.fn()
    const onIntuitionKindsChange = vi.fn()
    const onPacketSizeChange = vi.fn()
    const onFeedbackModeChange = vi.fn()

    render(
      <MissionComposer
        missionText="训练函数图像的结构直觉"
        subject="高中数学"
        count="3"
        difficulty="中等"
        questionType=""
        useStudyArchive
        useReferenceQuestions
        referenceSource="any"
        referenceYearRange="all"
        practiceGoal="structural_intuition"
        intuitionKinds={['prediction', 'representation', 'invariant']}
        packetSize={3}
        feedbackMode="guided"
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
        onPracticeGoalChange={onPracticeGoalChange}
        onIntuitionKindsChange={onIntuitionKindsChange}
        onPacketSizeChange={onPacketSizeChange}
        onFeedbackModeChange={onFeedbackModeChange}
        onModeChange={vi.fn()}
        onGenerate={vi.fn()}
      />
    )

    expect(screen.getByLabelText('直觉练习设置')).toBeInTheDocument()
    expect(screen.getByText('随原线路生成')).toBeInTheDocument()

    await user.click(screen.getByLabelText('练习目标'))
    await user.click(screen.getByRole('option', { name: '解法品鉴' }))
    expect(onPracticeGoalChange).toHaveBeenCalledWith('solution_appreciation')
    expect(onPacketSizeChange).toHaveBeenCalledWith(4)

    await user.click(screen.getByText('更多直觉控制'))
    await user.click(screen.getByRole('button', { name: '试探边界' }))
    expect(onIntuitionKindsChange).toHaveBeenCalledWith([
      'prediction',
      'representation',
      'invariant',
      'boundary',
    ])

    await user.click(screen.getByLabelText('环节数'))
    await user.click(screen.getByRole('option', { name: '每题 5 个直觉环节' }))
    expect(onPacketSizeChange).toHaveBeenLastCalledWith(5)

    await user.click(screen.getByLabelText('反馈方式'))
    await user.click(screen.getByRole('option', { name: '反思追问' }))
    expect(onFeedbackModeChange).toHaveBeenCalledWith('reflective')
  })
})
