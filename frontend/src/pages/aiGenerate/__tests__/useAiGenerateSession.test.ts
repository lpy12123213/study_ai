import { describe, expect, it } from 'vitest'
import type { QuestionLibraryDraftPreview } from '@/pages/questionLibrary/hooks/useQuestionLibraryTasks'
import { applyRegeneratedDraftSection, createQueuedSession, reduceTaskPreviewToSession } from '@/pages/aiGenerate/useAiGenerateSession'

describe('reduceTaskPreviewToSession', () => {
  it('maps preview drafts into ordered studio cards', () => {
    const preview: QuestionLibraryDraftPreview = {
      previewId: 'preview-001',
      subject: '高中数学',
      topic: '函数单调性',
      count: 2,
      taskId: 'task-001',
      draftQuestions: [
        {
          question_id: 'q-001',
          stem: '已知函数 f(x)，判断其单调区间。',
          answer: '在区间 (0, +∞) 单调递增。',
          analysis: '先求导，再由导数符号判断单调性。',
          keep: true,
        },
        {
          question_id: 'q-002',
          stem: '若函数 g(x) 在 R 上可导，讨论其极值点。',
          answer: 'x = 1 是极大值点。',
          analysis: '结合一阶导数与二阶导数判断。',
          keep: false,
        },
      ],
    }

    const session = reduceTaskPreviewToSession(preview)

    expect(session.previewId).toBe('preview-001')
    expect(session.mission.subject).toBe('高中数学')
    expect(session.drafts).toHaveLength(2)
    expect(session.drafts[0].title).toBe('题目 01')
    expect(session.drafts[0].sections.stem.content).toBe('已知函数 f(x)，判断其单调区间。')
    expect(session.drafts[0].sections.stem.status).toBe('done')
    expect(session.drafts[0].sections.answer.status).toBe('done')
    expect(session.drafts[0].sections.analysis.status).toBe('done')
    expect(session.drafts[1].keep).toBe(false)
    expect(session.confirmedIds).toEqual([])
  })

  it('creates queued placeholder cards before preview arrives', () => {
    const session = createQueuedSession({
      taskId: 'task-queued',
      subject: '高中数学',
      topic: '导数大题',
      count: 3,
    })

    expect(session.drafts).toHaveLength(3)
    expect(session.drafts[0].status).toBe('streaming')
    expect(session.drafts[0].sections.stem.status).toBe('streaming')
    expect(session.drafts[1].status).toBe('queued')
    expect(session.drafts[1].sections.stem.status).toBe('idle')
  })

  it('applies a regenerated section payload to the matching draft', () => {
    const preview: QuestionLibraryDraftPreview = {
      previewId: 'preview-001',
      subject: '高中数学',
      topic: '函数单调性',
      count: 1,
      taskId: 'task-001',
      draftQuestions: [
        {
          question_id: 'q-001',
          stem: '已知函数 \\(f(x)=x^2+1\\)，判断其单调区间。',
          answer: '在区间 \\((0,+\\infty)\\) 单调递增。',
          analysis: '旧解析',
          keep: true,
        },
      ],
    }

    const session = reduceTaskPreviewToSession(preview)
    const next = applyRegeneratedDraftSection(session, 'q-001', 'analysis', '新解析：由 \\(f\'(x)=2x\\) 的符号判断。')

    expect(next.drafts[0].status).toBe('ready')
    expect(next.drafts[0].sections.analysis.content).toBe('新解析：由 \\(f\'(x)=2x\\) 的符号判断。')
    expect(next.drafts[0].sections.analysis.status).toBe('done')
    expect(next.drafts[0].sections.analysis.edited).toBe(false)
  })
})
