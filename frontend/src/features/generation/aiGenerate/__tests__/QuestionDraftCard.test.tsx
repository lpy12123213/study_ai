import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QuestionDraftCard } from '@/features/generation/aiGenerate/QuestionDraftCard'
import type { AiGenerateDraftCard } from '@/features/generation/aiGenerate/types'

const clientMocks = vi.hoisted(() => ({
  downloadObjectUrl: vi.fn(),
  resolveApiResourceUrl: vi.fn((url: string) => `https://example.test${url.startsWith('/') ? url : `/${url}`}`),
}))
const practiceMocks = vi.hoisted(() => ({
  saveQuestionLibraryPracticeState: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  downloadObjectUrl: clientMocks.downloadObjectUrl,
  resolveApiResourceUrl: clientMocks.resolveApiResourceUrl,
}))

vi.mock('@/api/questionLibrary', async () => {
  const actual = await vi.importActual<typeof import('@/api/questionLibrary')>('@/api/questionLibrary')
  return {
    ...actual,
    saveQuestionLibraryPracticeState: practiceMocks.saveQuestionLibraryPracticeState,
  }
})

describe('QuestionDraftCard', () => {
  afterEach(() => cleanup())

  beforeEach(() => {
    vi.clearAllMocks()
    clientMocks.downloadObjectUrl.mockResolvedValue({
      objectUrl: 'blob:diagram-1',
      revoke: vi.fn(),
    })
    practiceMocks.saveQuestionLibraryPracticeState.mockResolvedValue({
      success: true,
      session_id: 'session-001',
      question_id: 'q-intuition',
      practice_state: {},
    })
  })

  it('renders all artifact sections and loads generated diagrams through authenticated blob URLs', async () => {
    const diagramUrl = `/api/media/generated/${'a'.repeat(64)}.png`
    const draft: AiGenerateDraftCard = {
      id: 'draft-card-1',
      questionId: 'q-001',
      title: '题目 01',
      index: 0,
      keep: true,
      status: 'ready',
      reviewStatus: 'pending_review',
      review: null,
      diagrams: [
        {
          url: diagramUrl,
          alt: '双轨模型实验装置示意图',
          caption: '图1: 双轨模型实验装置图',
        },
      ],
      sections: {
        stem: {
          label: '题干',
          content: '已知函数 \\(f(x)=x^2+1\\)，判断其单调区间。',
          status: 'done',
          updatedAt: '2026-03-13T12:00:00.000Z',
          locked: false,
          edited: false,
        },
        answer: {
          label: '答案',
          content: '在区间 (0, +∞) 单调递增。',
          status: 'done',
          updatedAt: '2026-03-13T12:00:01.000Z',
          locked: false,
          edited: false,
        },
        analysis: {
          label: '解析',
          content: '先求导，再由导数符号判断单调性。',
          status: 'done',
          updatedAt: '2026-03-13T12:00:02.000Z',
          locked: false,
          edited: true,
        },
      },
    }

    const { container } = render(
      <MemoryRouter>
        <QuestionDraftCard draft={draft} sessionId="session-001" />
      </MemoryRouter>
    )

    expect(screen.getByText('题目 01')).toBeInTheDocument()
    expect(screen.getByText('题干')).toBeInTheDocument()
    expect(screen.getByText('答案')).toBeInTheDocument()
    expect(screen.getByText('解析')).toBeInTheDocument()
    expect(screen.getByText('待审查')).toBeInTheDocument()
    expect(await screen.findByRole('textbox', { name: '题干' })).toHaveTextContent('已知函数')
    expect(screen.getByRole('link', { name: '进入审查' })).toHaveAttribute('href', '/ai-generate/review/session-001/q-001')
    expect(screen.getByRole('button', { name: '审核通过并入库' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '重生成解析' })).toBeInTheDocument()
    expect(screen.getByText('已手动调整')).toBeInTheDocument()
    expect(screen.getByText('图1: 双轨模型实验装置图')).toBeInTheDocument()
    const diagram = await screen.findByAltText('双轨模型实验装置示意图')
    await waitFor(() => expect(diagram).toHaveAttribute('src', 'blob:diagram-1'))
    expect(clientMocks.downloadObjectUrl).toHaveBeenCalledWith(diagramUrl)
    expect(container.querySelector('.katex')).not.toBeNull()
  })

  it('keeps reference answers hidden until the intuition stages have been attempted and persists key progress', async () => {
    const user = userEvent.setup()
    const draft: AiGenerateDraftCard = {
      id: 'draft-intuition',
      questionId: 'q-intuition',
      title: '题目 01',
      index: 0,
      keep: true,
      status: 'ready',
      reviewStatus: 'pending_review',
      review: null,
      intuitionPacket: {
        version: '1.0',
        practice_goal: 'structural_intuition',
        atom: {
          concept: '函数单调性',
          internal_model: '把函数想成随输入移动的高度变化',
          mental_action: '先看图像走势，再转成导数符号',
          decisive_cue: '导数符号',
          expected_first_feel: '先减后增',
          common_false_intuition: '只看一个点判断整体',
          formal_anchor: '导数符号表',
          transfer_mutation: '从图像改为参数表达式',
          boundary_flip: '临界参数处单调性改变',
          feedback: '比较直觉与符号表的差异',
        },
        stages: [
          {
            stage: 'perception',
            kind: 'prediction',
            prompt: '暂不求导，先判断图像的大致走势。',
            hint: '观察对称轴。',
            expected_answer: '图像先减后增。',
            feedback: '第一感觉应来自整体形状，而不是代入单点。',
          },
          {
            stage: 'model_externalization',
            kind: 'representation',
            prompt: '用一句话描述你脑中的图像。',
          },
          {
            stage: 'transfer',
            kind: 'invariant',
            prompt: '系数改变后，什么结构仍然保留？',
          },
        ],
      },
      sections: {
        stem: {
          label: '题干', content: '讨论函数的单调性。', status: 'done', updatedAt: null, locked: false, edited: false,
        },
        answer: {
          label: '答案', content: '先减后增。', status: 'done', updatedAt: null, locked: false, edited: false,
        },
        analysis: {
          label: '解析', content: '由导数符号判断。', status: 'done', updatedAt: null, locked: false, edited: false,
        },
      },
    }

    const { unmount } = render(
      <MemoryRouter>
        <QuestionDraftCard draft={draft} sessionId="session-001" />
      </MemoryRouter>
    )

    expect(screen.getByLabelText('直觉练习包')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '答案' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: '提交本步并查看反馈' })[0]).toBeDisabled()

    await user.type(screen.getByRole('textbox', { name: '第一感觉作答' }), '我猜图像先减后增')
    await user.click(screen.getAllByRole('button', { name: '提交本步并查看反馈' })[0]!)
    expect(await screen.findByText('图像先减后增。')).toBeInTheDocument()
    expect(practiceMocks.saveQuestionLibraryPracticeState).toHaveBeenCalledWith(
      'session-001',
      'q-intuition',
      expect.objectContaining({
        phase: 'perception',
        first_guess: '我猜图像先减后增',
        confidence: 50,
        stage_responses: {
          perception: expect.objectContaining({
            initial_response: '我猜图像先减后增',
            final_response: '我猜图像先减后增',
          }),
        },
      })
    )

    const revised = screen.getByRole('textbox', { name: '第一感觉校准后作答' })
    await user.clear(revised)
    await user.type(revised, '我改为根据对称轴判断先减后增')
    practiceMocks.saveQuestionLibraryPracticeState.mockRejectedValueOnce(new Error('offline'))
    await user.click(screen.getByRole('button', { name: '保存本步修正' }))
    expect(await screen.findByText('保存失败，当前页面仍保留作答')).toBeInTheDocument()
    expect(revised).toHaveValue('我改为根据对称轴判断先减后增')

    await user.type(screen.getByRole('textbox', { name: '说出脑中模型作答' }), '我看见一条先下降再上升的曲线')
    await user.type(screen.getByRole('textbox', { name: '换个表面再试作答' }), '开口方向和对称结构仍保留')
    practiceMocks.saveQuestionLibraryPracticeState.mockRejectedValueOnce(new Error('offline-on-complete'))
    await user.click(screen.getByRole('button', { name: '完成练习，查看答案与解析' }))
    expect(await screen.findByText('保存失败，当前页面仍保留作答')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '答案' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '完成练习，查看答案与解析' }))
    expect(await screen.findByRole('textbox', { name: '答案' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '解析' })).toBeInTheDocument()
    await waitFor(() => {
      expect(practiceMocks.saveQuestionLibraryPracticeState).toHaveBeenLastCalledWith(
        'session-001',
        'q-intuition',
        expect.objectContaining({ completed: true })
      )
    })

    unmount()
    render(
      <MemoryRouter>
        <QuestionDraftCard draft={{ ...draft, practiceState: { completed: true } }} sessionId="session-001" />
      </MemoryRouter>
    )
    expect(screen.getByRole('textbox', { name: '答案' })).toBeInTheDocument()
  }, 15_000)

  it('syncs persisted practice progress on a stable-card rerender without overwriting nested initial answers', async () => {
    const draft: AiGenerateDraftCard = {
      id: 'draft-stable',
      questionId: 'q-stable',
      title: '题目 01',
      index: 0,
      keep: true,
      status: 'ready',
      reviewStatus: 'pending_review',
      review: null,
      intuitionPacket: {
        version: '1.0',
        practice_goal: 'structural_intuition',
        atom: {
          concept: '函数单调性',
          internal_model: '观察图像变化',
          mental_action: '先猜后证',
          decisive_cue: '导数符号',
          expected_first_feel: '先减后增',
          common_false_intuition: '只看局部',
          formal_anchor: '符号表',
          transfer_mutation: '更换表示',
          boundary_flip: '临界参数',
          feedback: '对照修正',
        },
        stages: [{ stage: 'perception', kind: 'prediction', prompt: '先判断走势。' }],
      },
      practiceState: {
        phase: 'perception',
        first_guess: '顶层旧初答',
        final_response: '顶层旧修正',
        confidence: 40,
        hint_level: 1,
        stage_responses: {
          perception: {
            initial_response: '嵌套初答',
            final_response: '嵌套修正',
            confidence: 40,
            hint_level: 1,
          },
        },
      },
      sections: {
        stem: { label: '题干', content: '讨论单调性。', status: 'done', updatedAt: null, locked: false, edited: false },
        answer: { label: '答案', content: '标准答案。', status: 'done', updatedAt: null, locked: false, edited: false },
        analysis: { label: '解析', content: '标准解析。', status: 'done', updatedAt: null, locked: false, edited: false },
      },
    }

    const { rerender } = render(
      <MemoryRouter>
        <QuestionDraftCard draft={draft} sessionId="session-001" />
      </MemoryRouter>
    )

    expect(screen.getByRole('textbox', { name: '第一感觉作答' })).toHaveValue('嵌套初答')
    expect(screen.getByRole('textbox', { name: '第一感觉校准后作答' })).toHaveValue('嵌套修正')
    expect(screen.queryByRole('textbox', { name: '答案' })).not.toBeInTheDocument()

    rerender(
      <MemoryRouter>
        <QuestionDraftCard
          draft={{
            ...draft,
            practiceState: {
              ...draft.practiceState,
              completed: true,
              confidence: 80,
              reflection: '服务端已保存反思',
              stage_responses: {
                perception: {
                  initial_response: '服务端新初答',
                  final_response: '服务端新修正',
                  confidence: 80,
                  hint_level: 1,
                },
              },
            },
          }}
          sessionId="session-001"
        />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: '第一感觉作答' })).toHaveValue('服务端新初答')
    })
    expect(screen.getByRole('textbox', { name: '第一感觉校准后作答' })).toHaveValue('服务端新修正')
    expect(screen.getByRole('textbox', { name: '一句话反思' })).toHaveValue('服务端已保存反思')
    expect(screen.getByRole('textbox', { name: '答案' })).toBeInTheDocument()
  })
})
