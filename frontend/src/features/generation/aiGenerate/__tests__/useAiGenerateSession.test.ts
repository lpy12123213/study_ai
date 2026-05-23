import { describe, expect, it } from 'vitest'
import type { QuestionLibrarySessionDetail } from '@/api/questionLibrary'
import type { QuestionLibraryDraftPreview } from '@/features/generation/questionLibrary/hooks/useQuestionLibraryTasks'
import {
  applyRegeneratedDraftSection,
  createQueuedSession,
  reduceSessionDetailToSession,
  reduceTaskPreviewToSession,
  setSessionStopRequested,
  toggleDraftConfirmed,
} from '@/features/generation/aiGenerate/useAiGenerateSession'

describe('reduceTaskPreviewToSession', () => {
  it('maps preview drafts into ordered studio cards', () => {
    const preview: QuestionLibraryDraftPreview = {
      previewId: 'preview-001',
      sessionId: 'session-001',
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
      sessionId: 'session-001',
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

  it('restores persisted session detail with reasoning blocks and confirmed drafts', () => {
    const detail: QuestionLibrarySessionDetail = {
      session_id: 'session-001',
      preview_id: 'preview-001',
      status: 'pending_review',
      mode: 'infinite',
      subject: '高中数学',
      topic: '函数单调性',
      count: 2,
      task_ids: ['task-001'],
      latest_task_id: 'task-001',
      updated_at_s: 1710000000,
      created_at_s: 1710000000,
      reasoning_blocks_count: 2,
      confirmed_question_ids: ['q-001'],
      stop_requested: true,
      difficulty: '中等',
      question_type: '解答题',
      grade_id: 'grade-1',
      textbook_version_id: 'textbook-1',
      knowledge_point_ids: ['kp-1'],
      knowledge_points: ['函数单调性'],
      stream_reasoning: true,
      use_study_archive: true,
      draft_questions: [
        {
          question_id: 'q-001',
          stem: '题干 1',
          answer: '答案 1',
          analysis: '解析 1',
          keep: true,
          review_status: 'confirmed',
          review: {
            verdict: '通过',
            overall_score: 93,
            dimensions: [{ name: '准确性', score: 10, comment: '表达准确' }],
            highlights: ['结构完整'],
            issues: [],
            summary: '适合入库',
            model: 'gpt-5-mini',
          },
        },
        {
          question_id: 'q-002',
          stem: '题干 2',
          answer: '答案 2',
          analysis: '解析 2',
          keep: true,
          review_status: 'pending_review',
          review: null,
        },
      ],
      reasoning_blocks: [
        {
          id: 'reason-1',
          task_id: 'task-001',
          stage_id: 'judge',
          stage_label: '判题筛选',
          source: 'raw',
          content: '先确认区分度和答案一致性。',
          created_at: '2026-03-20T10:00:00Z',
        },
      ],
      task_events: [
        {
          taskId: 'task-001',
          seq: 12,
          type: 'reasoning_status',
          data: {
            stage_id: 'judge',
            stage_label: '判题筛选',
            mode: 'trace',
            message: '当前模型未返回原始 reasoning，已降级为事件级 trace。',
          },
          created_at: '2026-03-20T10:00:01Z',
        },
      ],
    }

    const session = reduceSessionDetailToSession(detail)

    expect(session.sessionId).toBe('session-001')
    expect(session.mode).toBe('infinite')
    expect(session.stopRequested).toBe(true)
    expect(session.mission.gradeId).toBe('grade-1')
    expect(session.mission.textbookVersionId).toBe('textbook-1')
    expect(session.mission.knowledgePointIds).toEqual(['kp-1'])
    expect(session.confirmedIds).toEqual(['q-001'])
    expect(session.drafts[0].reviewStatus).toBe('confirmed')
    expect(session.reasoningBlocks[0].source).toBe('raw')
    expect(session.taskEvents[0]?.type).toBe('reasoning_status')
  })

  it('marks ready drafts as committed on a single confirm action', () => {
    const session = createQueuedSession({
      taskId: 'task-queued',
      subject: '高中数学',
      topic: '导数',
      count: 2,
    })

    session.drafts[0].questionId = 'q-001'
    session.drafts[0].reviewStatus = 'approved'
    session.drafts[0].status = 'ready'
    session.drafts[1].questionId = 'q-002'
    session.drafts[1].reviewStatus = 'pending_review'
    session.drafts[1].status = 'ready'

    const next = toggleDraftConfirmed(session, 'q-001')
    const following = toggleDraftConfirmed(next, 'q-002')

    expect(next.confirmedIds).toEqual(['q-001'])
    expect(next.drafts[0].reviewStatus).toBe('committed')
    expect(following.confirmedIds).toEqual(['q-001', 'q-002'])
    expect(following.drafts[1].reviewStatus).toBe('committed')
  })

  it('marks the session as stopped when the user requests infinite mode to stop', () => {
    const session = createQueuedSession({
      sessionId: 'session-queued',
      taskId: 'task-queued',
      subject: '高中数学',
      topic: '导数',
      count: 2,
      mode: 'infinite',
    })

    const next = setSessionStopRequested(session, true)

    expect(next.stopRequested).toBe(true)
    expect(next.status).toBe('stopped')
  })
})
