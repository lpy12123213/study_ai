import type {
  QuestionLibraryDraftQuestion,
  QuestionLibrarySessionDetail,
} from '@/api/questionLibrary'
import { generateId } from '@/lib/utils'
import type { QuestionLibraryDraftPreview } from '@/pages/questionLibrary/hooks/useQuestionLibraryTasks'
import type {
  AiGenerateDraftCard,
  AiGenerateReasonBlock,
  AiGenerateReviewStatus,
  AiGenerateSessionMode,
  AiGenerateStudioSession,
} from '@/pages/aiGenerate/types'

function nowIso(): string {
  return new Date().toISOString()
}

function toReviewStatus(value: unknown): AiGenerateReviewStatus {
  const raw = String(value || '').trim()
  if (raw === 'in_review' || raw === 'approved' || raw === 'rejected' || raw === 'confirmed' || raw === 'committed') {
    return raw
  }
  return 'pending_review'
}

function reviewStatusLabel(status: AiGenerateReviewStatus): AiGenerateDraftCard['status'] {
  if (status === 'rejected') return 'failed'
  return 'ready'
}

function buildSection(label: string, content: string, status?: 'idle' | 'streaming' | 'done' | 'failed') {
  const value = String(content || '').trim()
  return {
    label,
    content: value,
    status: status ?? (value ? 'done' : 'idle'),
    updatedAt: value || status === 'streaming' ? nowIso() : null,
    locked: false,
    edited: false,
  }
}

function mapDraftQuestion(
  index: number,
  input: QuestionLibraryDraftQuestion,
  confirmedIds: string[],
): AiGenerateDraftCard {
  const reviewStatus = toReviewStatus(input.review_status)
  const questionId = String(input.question_id || '').trim()
  return {
    id: `draft-card-${index + 1}-${questionId || generateId()}`,
    questionId,
    title: `题目 ${String(index + 1).padStart(2, '0')}`,
    index,
    keep: confirmedIds.includes(questionId) ? true : input.keep !== false,
    status: reviewStatusLabel(reviewStatus),
    reviewStatus,
    review: input.review
      ? {
          verdict: String(input.review.verdict || '').trim(),
          overallScore: Number(input.review.overall_score || 0),
          dimensions: (input.review.dimensions || []).map((item) => ({
            name: String(item.name || '').trim(),
            score: Number(item.score || 0),
            comment: String(item.comment || '').trim(),
          })),
          highlights: [...(input.review.highlights || [])],
          issues: [...(input.review.issues || [])],
          summary: String(input.review.summary || '').trim(),
          model: String(input.review.model || '').trim(),
        }
      : null,
    diagrams: Array.isArray(input.diagrams)
      ? input.diagrams
          .filter((item) => item && typeof item === 'object' && typeof item.url === 'string')
          .map((item) => ({
            kind: typeof item.kind === 'string' ? item.kind : undefined,
            url: String(item.url || '').trim(),
            filename: typeof item.filename === 'string' ? item.filename : undefined,
            mediaId: typeof item.media_id === 'string' ? item.media_id : undefined,
            alt: typeof item.alt === 'string' ? item.alt : undefined,
            caption: typeof item.caption === 'string' ? item.caption : undefined,
            markdown: typeof item.markdown === 'string' ? item.markdown : undefined,
          }))
          .filter((item) => item.url)
      : undefined,
    sections: {
      stem: buildSection('题干', input.stem),
      answer: buildSection('答案', input.answer),
      analysis: buildSection('解析', input.analysis),
    },
  }
}

function normalizeReasonBlocks(input: unknown): AiGenerateReasonBlock[] {
  if (!Array.isArray(input)) return []
  return input
    .filter((item) => item && typeof item === 'object')
    .map((item: any) => ({
      id: String(item.id || generateId()),
      taskId: String(item.task_id || item.taskId || '').trim() || undefined,
      stageId: String(item.stage_id || item.stageId || '').trim() || undefined,
      stageLabel: String(item.stage_label || item.stageLabel || '').trim() || undefined,
      source: String(item.source || '').trim() || 'trace',
      content: String(item.content || '').trim(),
      createdAt: String(item.created_at || item.createdAt || '').trim() || undefined,
    }))
    .filter((item) => item.content)
}

export function reduceTaskPreviewToSession(preview: QuestionLibraryDraftPreview): AiGenerateStudioSession {
  const confirmedIds = (preview.draftQuestions || [])
    .filter((item) => {
      const status = toReviewStatus(item.review_status)
      return status === 'confirmed' || status === 'committed'
    })
    .map((item) => String(item.question_id || '').trim())
    .filter(Boolean)
  return {
    sessionId: String(preview.sessionId || '').trim(),
    previewId: String(preview.previewId || '').trim(),
    taskId: String(preview.taskId || '').trim(),
    status: 'pending_review',
    mode: (String(preview.mode || 'standard').trim() || 'standard') as AiGenerateSessionMode,
    stopRequested: false,
    mission: {
      subject: String(preview.subject || '').trim(),
      topic: String(preview.topic || '').trim(),
      count: Math.max(0, Number(preview.count || 0)),
      useStudyArchive: undefined,
      useReferenceQuestions: preview.useReferenceQuestions !== false,
      referenceSource: String(preview.referenceSource || 'any').trim() || 'any',
      referenceYearRange: String(preview.referenceYearRange || 'all').trim() || 'all',
    },
    drafts: (preview.draftQuestions || []).map((item, index) => mapDraftQuestion(index, item, confirmedIds)),
    confirmedIds,
    reasoningBlocks: [],
    taskEvents: [],
  }
}

export function reduceSessionDetailToSession(detail: QuestionLibrarySessionDetail): AiGenerateStudioSession {
  const confirmedIds = Array.isArray(detail.confirmed_question_ids)
    ? detail.confirmed_question_ids.map((item) => String(item || '').trim()).filter(Boolean)
    : []
  return {
    sessionId: String(detail.session_id || '').trim(),
    previewId: String(detail.preview_id || '').trim(),
    taskId: String(detail.latest_task_id || '').trim(),
    status: String(detail.status || '').trim(),
    mode: (String(detail.mode || 'standard').trim() || 'standard') as AiGenerateSessionMode,
    stopRequested: Boolean(detail.stop_requested),
    mission: {
      subject: String(detail.subject || '').trim(),
      topic: String(detail.topic || '').trim(),
      count: Math.max(0, Number(detail.count || 0)),
      difficulty: String((detail as any).difficulty || '').trim(),
      questionType: String((detail as any).question_type || '').trim(),
      useStudyArchive: Boolean((detail as any).use_study_archive),
      useReferenceQuestions: (detail as any).use_reference_questions !== false,
      referenceSource: String((detail as any).reference_source || 'any').trim() || 'any',
      referenceYearRange: String((detail as any).reference_year_range || 'all').trim() || 'all',
      gradeId: String((detail as any).grade_id || '').trim(),
      textbookVersionId: String((detail as any).textbook_version_id || '').trim(),
      knowledgePointIds: [...((detail as any).knowledge_point_ids || [])],
      knowledgePoints: [...((detail as any).knowledge_points || [])],
    },
    drafts: (detail.draft_questions || []).map((item, index) => mapDraftQuestion(index, item, confirmedIds)),
    confirmedIds,
    reasoningBlocks: normalizeReasonBlocks(detail.reasoning_blocks),
    taskEvents: Array.isArray(detail.task_events) ? detail.task_events : [],
  }
}

export function createQueuedSession(input: {
  sessionId?: string
  taskId: string
  subject: string
  topic: string
  count: number
  mode?: AiGenerateSessionMode
  difficulty?: string
  questionType?: string
  useStudyArchive?: boolean
  useReferenceQuestions?: boolean
  referenceSource?: 'any' | 'gaokao' | 'mock' | 'joint' | string
  referenceYearRange?: 'all' | '3' | '5' | string
  gradeId?: string
  textbookVersionId?: string
  knowledgePointIds?: string[]
  knowledgePoints?: string[]
}): AiGenerateStudioSession {
  const count = Math.max(1, Math.min(Number(input.count || 1), 10))
  const drafts: AiGenerateDraftCard[] = Array.from({ length: count }).map((_, index) => {
    const isActive = index === 0
    return {
      id: `queued-${generateId()}`,
      questionId: `pending-${String(index + 1).padStart(2, '0')}`,
      title: `题目 ${String(index + 1).padStart(2, '0')}`,
      index,
      keep: true,
      status: isActive ? 'streaming' : 'queued',
      reviewStatus: 'pending_review',
      review: null,
      sections: {
        stem: buildSection('题干', '', isActive ? 'streaming' : 'idle'),
        answer: buildSection('答案', '', 'idle'),
        analysis: buildSection('解析', '', 'idle'),
      },
    }
  })

  return {
    sessionId: String(input.sessionId || '').trim(),
    previewId: '',
    taskId: String(input.taskId || '').trim(),
    status: 'running',
    mode: input.mode || 'standard',
    stopRequested: false,
    mission: {
      subject: String(input.subject || '').trim(),
      topic: String(input.topic || '').trim(),
      count,
      difficulty: String(input.difficulty || '').trim(),
      questionType: String(input.questionType || '').trim(),
      useStudyArchive: Boolean(input.useStudyArchive),
      useReferenceQuestions: input.useReferenceQuestions !== false,
      referenceSource: String(input.referenceSource || 'any').trim() || 'any',
      referenceYearRange: String(input.referenceYearRange || 'all').trim() || 'all',
      gradeId: String(input.gradeId || '').trim(),
      textbookVersionId: String(input.textbookVersionId || '').trim(),
      knowledgePointIds: [...(input.knowledgePointIds || [])],
      knowledgePoints: [...(input.knowledgePoints || [])],
    },
    drafts,
    confirmedIds: [],
    reasoningBlocks: [],
    taskEvents: [],
  }
}

function updateDraft(
  session: AiGenerateStudioSession,
  questionId: string,
  updater: (draft: AiGenerateDraftCard) => AiGenerateDraftCard
): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  return {
    ...session,
    drafts: session.drafts.map((draft) => (draft.questionId === targetId ? updater(draft) : draft)),
  }
}

export function updateDraftSection(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections'],
  content: string
): AiGenerateStudioSession {
  return updateDraft(session, questionId, (draft) => ({
    ...draft,
    sections: {
      ...draft.sections,
      [sectionKey]: {
        ...draft.sections[sectionKey],
        content,
        edited: true,
        status: content.trim() ? 'done' : 'idle',
        updatedAt: nowIso(),
      },
    },
  }))
}

export function toggleDraftSectionLock(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections']
): AiGenerateStudioSession {
  return updateDraft(session, questionId, (draft) => ({
    ...draft,
    sections: {
      ...draft.sections,
      [sectionKey]: {
        ...draft.sections[sectionKey],
        locked: !draft.sections[sectionKey].locked,
      },
    },
  }))
}

export function markDraftSectionRegenerating(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections']
): AiGenerateStudioSession {
  return updateDraft(session, questionId, (draft) => ({
    ...draft,
    status: 'streaming',
    sections: {
      ...draft.sections,
      [sectionKey]: {
        ...draft.sections[sectionKey],
        status: 'streaming',
        updatedAt: nowIso(),
      },
    },
  }))
}

export function finalizeDraftSectionRegeneration(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections']
): AiGenerateStudioSession {
  return updateDraft(session, questionId, (draft) => ({
    ...draft,
    status: reviewStatusLabel(draft.reviewStatus),
    sections: {
      ...draft.sections,
      [sectionKey]: {
        ...draft.sections[sectionKey],
        status: draft.sections[sectionKey].content.trim() ? 'done' : 'idle',
        updatedAt: nowIso(),
      },
    },
  }))
}

export function applyRegeneratedDraftSection(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections'],
  content: string
): AiGenerateStudioSession {
  return updateDraft(session, questionId, (draft) => ({
    ...draft,
    status: reviewStatusLabel(draft.reviewStatus),
    sections: {
      ...draft.sections,
      [sectionKey]: {
        ...draft.sections[sectionKey],
        content,
        status: content.trim() ? 'done' : 'idle',
        updatedAt: nowIso(),
        edited: false,
      },
    },
  }))
}

export function failDraftSectionRegeneration(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections']
): AiGenerateStudioSession {
  return updateDraft(session, questionId, (draft) => ({
    ...draft,
    status: 'failed',
    sections: {
      ...draft.sections,
      [sectionKey]: {
        ...draft.sections[sectionKey],
        status: 'failed',
        updatedAt: nowIso(),
      },
    },
  }))
}

export function canConfirmDraft(draft: AiGenerateDraftCard): boolean {
  return draft.status === 'ready' && draft.reviewStatus !== 'rejected' && draft.reviewStatus !== 'committed'
}

export function toggleDraftConfirmed(session: AiGenerateStudioSession, questionId: string): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  const draft = session.drafts.find((item) => item.questionId === targetId)
  if (!draft || !canConfirmDraft(draft)) return session
  return {
    ...session,
    confirmedIds: session.confirmedIds.includes(targetId) ? session.confirmedIds : [...session.confirmedIds, targetId],
    drafts: session.drafts.map((item) =>
      item.questionId === targetId
        ? {
            ...item,
            reviewStatus: 'committed',
          }
        : item
    ),
  }
}

export function applyReviewedDraft(
  session: AiGenerateStudioSession,
  questionId: string,
  reviewStatus: AiGenerateReviewStatus,
  review: AiGenerateDraftCard['review']
): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  return {
    ...session,
    confirmedIds:
      reviewStatus === 'rejected'
        ? session.confirmedIds.filter((item) => item !== targetId)
        : session.confirmedIds,
    drafts: session.drafts.map((draft) =>
      draft.questionId === targetId
        ? {
            ...draft,
            reviewStatus,
            review,
            status: reviewStatus === 'rejected' ? 'failed' : 'ready',
          }
        : draft
    ),
  }
}

export function setSessionStopRequested(session: AiGenerateStudioSession, stopRequested: boolean): AiGenerateStudioSession {
  return {
    ...session,
    stopRequested,
    status: stopRequested ? 'stopped' : session.status,
  }
}

export function toCommitQuestions(session: AiGenerateStudioSession): QuestionLibraryDraftQuestion[] {
  const confirmed = new Set(session.confirmedIds)
  return session.drafts.map((draft) => ({
    question_id: draft.questionId,
    stem: draft.sections.stem.content,
    answer: draft.sections.answer.content,
    analysis: draft.sections.analysis.content,
    keep: confirmed.has(draft.questionId),
    review_status: draft.reviewStatus,
    review: draft.review
      ? {
          verdict: draft.review.verdict,
          overall_score: draft.review.overallScore,
          dimensions: draft.review.dimensions,
          highlights: draft.review.highlights,
          issues: draft.review.issues,
          summary: draft.review.summary,
          model: draft.review.model,
        }
      : null,
  }))
}
