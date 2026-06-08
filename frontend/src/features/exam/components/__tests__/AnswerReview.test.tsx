import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AnswerReview } from '@/features/exam/components/AnswerReview'
import type { ExamQuestion, ExamResult } from '@/types/exam'

const clientMocks = vi.hoisted(() => ({
  downloadObjectUrl: vi.fn(),
  resolveApiResourceUrl: vi.fn((url: string) => `https://example.test${url.startsWith('/') ? url : `/${url}`}`),
}))

vi.mock('@/api/client', () => ({
  downloadObjectUrl: clientMocks.downloadObjectUrl,
  resolveApiResourceUrl: clientMocks.resolveApiResourceUrl,
}))

describe('AnswerReview', () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    clientMocks.downloadObjectUrl.mockResolvedValue({
      objectUrl: 'blob:handwriting-review',
      revoke: vi.fn(),
    })
  })

  it('loads handwriting review images through authenticated blob URLs', async () => {
    const imageUrl = '/api/media/exam-handwriting/session-001/q-001.jpg'
    const questions: ExamQuestion[] = [
      {
        questionId: 'q-001',
        order: 1,
        type: 'calculation',
        questionType: 'calculation',
        stem: '写出计算过程。',
        maxScore: 10,
        studentAnswer: {
          questionId: 'q-001',
          questionType: 'calculation',
          selectedOptions: [],
          fillBlankText: '',
          handwritingImagePath: 'user-1/session-001/q-001.jpg',
          handwritingImageUrl: imageUrl,
          textAnswer: '',
        },
      },
    ]
    const result: ExamResult = {
      sessionId: 'session-001',
      totalScore: 8,
      maxScore: 10,
      scoreRatio: 0.8,
      objectiveCorrect: 0,
      objectiveTotal: 0,
      subjectiveScore: 8,
      subjectiveMax: 10,
      breakdown: [{ question_id: 'q-001', score: 8, max_score: 10 }],
      aiFeedback: {},
    }

    render(<AnswerReview questions={questions} result={result} />)

    const image = await screen.findByAltText('手写作答')
    await waitFor(() => expect(image).toHaveAttribute('src', 'blob:handwriting-review'))
    expect(clientMocks.downloadObjectUrl).toHaveBeenCalledWith(imageUrl)
  })

  it('renders review stems through the shared rich question renderer', async () => {
    const imageUrl = `/api/media/generated/${'d'.repeat(64)}.png`
    const formulaHash = '294f5ba74cdf695fc9a8a8e52f421328'
    const questions: ExamQuestion[] = [
      {
        questionId: 'q-rich-review',
        order: 1,
        type: 'single_choice',
        questionType: 'single_choice',
        stem: `已知 \\(x^2+1\\)，观察 \\[y=x^2\\]，参考[图片:${imageUrl}]和[公式:${formulaHash}]。`,
        maxScore: 5,
      },
    ]
    const result: ExamResult = {
      sessionId: 'session-001',
      totalScore: 5,
      maxScore: 5,
      scoreRatio: 1,
      objectiveCorrect: 1,
      objectiveTotal: 1,
      subjectiveScore: 0,
      subjectiveMax: 0,
      breakdown: [{ question_id: 'q-rich-review', score: 5, max_score: 5, is_correct: true }],
      aiFeedback: {},
    }

    const { container } = render(<AnswerReview questions={questions} result={result} />)

    expect(await screen.findByAltText('题目图片')).toBeInTheDocument()
    expect(await screen.findByAltText('题目公式')).toBeInTheDocument()
    await waitFor(() => expect(container.querySelector('.katex-display')).not.toBeNull())
    await waitFor(() => expect(screen.getByAltText('题目图片')).toHaveAttribute('src', 'blob:handwriting-review'))

    const renderedText = container.textContent || ''
    expect(renderedText).not.toContain('\\(')
    expect(renderedText).not.toContain('\\[')
    expect(renderedText).not.toContain('[图片:')
    expect(renderedText).not.toContain('[公式:')
  })
})
