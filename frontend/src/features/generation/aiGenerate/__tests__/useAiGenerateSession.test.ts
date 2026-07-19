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
  toCommitQuestions,
  updateDraftSection,
} from '@/features/generation/aiGenerate/useAiGenerateSession'
import { normalizeIntuitionPractice } from '@/features/generation/aiGenerate/types'

describe('normalizeIntuitionPractice', () => {
  it('reserves a fourth stage for solution appreciation', () => {
    expect(normalizeIntuitionPractice({
      practice_goal: 'solution_appreciation',
      intuition_kinds: ['solution_comparison'],
      packet_size: 3,
      feedback_mode: 'guided',
    }).packet_size).toBe(4)
  })
})

describe('reduceTaskPreviewToSession', () => {
  it('maps preview drafts into ordered studio cards', () => {
    const preview = {
      previewId: 'preview-001',
      sessionId: 'session-001',
      subject: '高中数学',
      topic: '函数单调性',
      count: 2,
      taskId: 'task-001',
      difficulty: '困难',
      questionType: '解答题',
      useStudyArchive: true,
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
    expect(session.mission.difficulty).toBe('困难')
    expect(session.mission.questionType).toBe('解答题')
    expect(session.mission.useStudyArchive).toBe(true)
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
    session.drafts[0].intuitionPacket = { version: '1.0', stages: [] } as any
    session.drafts[0].practiceState = { first_guess: '旧猜想' }
    const next = applyRegeneratedDraftSection(session, 'q-001', 'analysis', '新解析：由 \\(f\'(x)=2x\\) 的符号判断。')

    expect(next.drafts[0].status).toBe('ready')
    expect(next.drafts[0].sections.analysis.content).toBe('新解析：由 \\(f\'(x)=2x\\) 的符号判断。')
    expect(next.drafts[0].sections.analysis.status).toBe('done')
    expect(next.drafts[0].sections.analysis.edited).toBe(false)
    expect(next.drafts[0].intuitionPacket).toBeUndefined()
    expect(next.drafts[0].practiceState).toBeUndefined()

    const edited = updateDraftSection(session, 'q-001', 'stem', '手工调整后的题干')
    expect(edited.drafts[0].intuitionPacket).toBeUndefined()
    expect(edited.drafts[0].practiceState).toBeUndefined()
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
      intuition_practice: {
        practice_goal: 'transfer',
        intuition_kinds: ['prediction', 'representation'],
        packet_size: 4,
        feedback_mode: 'reflective',
      },
      practice_attempts: {
        'q-001': {
          phase: 'transfer',
          first_guess: '先猜单调递增',
          final_response: '结合导数后修正',
          confidence: 70,
          hint_level: 1,
          transfer_correct: true,
          reflection: '图像直觉需要用导数校准',
          completed: true,
        },
      },
      draft_questions: [
        {
          question_id: 'q-001',
          stem: '题干 1',
          answer: '答案 1',
          analysis: '解析 1',
          keep: true,
          review_status: 'confirmed',
          intuition_packet: {
            version: '1.0',
            practice_goal: 'transfer',
            atom: {
              concept: '函数单调性',
              internal_model: '图像随输入变化',
              mental_action: '观察走势',
              decisive_cue: '导数符号',
              expected_first_feel: '先减后增',
              common_false_intuition: '局部代替整体',
              formal_anchor: '符号表',
              transfer_mutation: '改成参数函数',
              boundary_flip: '临界参数',
              feedback: '比较猜想与证明',
            },
            stages: [
              { stage: 'perception', kind: 'prediction', prompt: '先判断走势。' },
              { stage: 'transfer', kind: 'representation', prompt: '换成图像再判断。' },
            ],
          },
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
    expect(session.mission.intuitionPractice).toEqual({
      practice_goal: 'transfer',
      intuition_kinds: ['prediction', 'representation'],
      packet_size: 4,
      feedback_mode: 'reflective',
    })
    expect(session.confirmedIds).toEqual(['q-001'])
    expect(session.drafts[0].reviewStatus).toBe('confirmed')
    expect(session.drafts[0].intuitionPacket?.stages).toHaveLength(2)
    expect(session.drafts[0].practiceState?.completed).toBe(true)
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

  it('keeps draft diagrams when building the preview commit payload', () => {
    const detail: QuestionLibrarySessionDetail = {
      session_id: 'session-media',
      preview_id: 'preview-media',
      status: 'pending_review',
      mode: 'standard',
      subject: '高中物理',
      topic: '电磁感应',
      count: 1,
      task_ids: ['task-media'],
      latest_task_id: 'task-media',
      updated_at_s: 1710000000,
      created_at_s: 1710000000,
      reasoning_blocks_count: 0,
      confirmed_question_ids: ['media-q-1'],
      stop_requested: false,
      draft_questions: [
        {
          question_id: 'media-q-1',
          stem: '观察图示回答问题。',
          answer: '答案',
          analysis: '解析',
          keep: true,
          review_status: 'confirmed',
          review: null,
          diagrams: [
            {
              kind: 'source',
              url: '/api/media/proxy?url=https%3A%2F%2Fzujuan.xkw.com%2Fstatic%2Fquestion.png',
              filename: 'question.png',
              media_id: 'media-1',
              alt: '导入原图',
              caption: '原始试题图片',
              markdown: '![导入原图](/api/media/proxy?url=https%3A%2F%2Fzujuan.xkw.com%2Fstatic%2Fquestion.png)',
            },
          ],
        },
      ],
      reasoning_blocks: [],
      task_events: [],
    }

    const session = reduceSessionDetailToSession(detail)
    const payload = toCommitQuestions(session)

    expect(payload[0].diagrams).toEqual(detail.draft_questions[0].diagrams)
  })
})
