import type { QuestionLibraryDraftQuestion } from '@/api/questionLibrary'
import { generateId } from '@/lib/utils'
import type { QuestionLibraryDraftPreview } from '@/pages/questionLibrary/hooks/useQuestionLibraryTasks'
import type { AiGenerateDraftCard, AiGenerateSectionState, AiGenerateStudioSession } from '@/pages/aiGenerate/types'

function nowIso(): string {
  return new Date().toISOString()
}

function buildSection(label: string, content: string, status?: AiGenerateSectionState['status']): AiGenerateSectionState {
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

function buildDraftCard(index: number, input: QuestionLibraryDraftPreview['draftQuestions'][number]): AiGenerateDraftCard {
  return {
    id: `draft-card-${index + 1}-${String(input.question_id || '').trim()}`,
    questionId: String(input.question_id || '').trim(),
    title: `题目 ${String(index + 1).padStart(2, '0')}`,
    index,
    keep: input.keep === false ? false : true,
    status: 'ready',
    sections: {
      stem: buildSection('题干', input.stem),
      answer: buildSection('答案', input.answer),
      analysis: buildSection('解析', input.analysis),
    },
  }
}

export function reduceTaskPreviewToSession(preview: QuestionLibraryDraftPreview): AiGenerateStudioSession {
  return {
    previewId: String(preview.previewId || '').trim(),
    taskId: String(preview.taskId || '').trim(),
    mission: {
      subject: String(preview.subject || '').trim(),
      topic: String(preview.topic || '').trim(),
      count: Math.max(0, Number(preview.count || 0)),
    },
    drafts: (preview.draftQuestions || []).map((item, index) => buildDraftCard(index, item)),
    confirmedIds: [],
  }
}

export function createQueuedSession(input: {
  taskId: string
  subject: string
  topic: string
  count: number
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
      sections: {
        stem: buildSection('题干', '', isActive ? 'streaming' : 'idle'),
        answer: buildSection('答案', '', 'idle'),
        analysis: buildSection('解析', '', 'idle'),
      },
    }
  })

  return {
    previewId: '',
    taskId: String(input.taskId || '').trim(),
    mission: {
      subject: String(input.subject || '').trim(),
      topic: String(input.topic || '').trim(),
      count,
    },
    drafts,
    confirmedIds: [],
  }
}

export function updateDraftSection(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections'],
  content: string
): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  return {
    ...session,
    drafts: session.drafts.map((draft) => {
      if (draft.questionId !== targetId) return draft
      const nextSection = {
        ...draft.sections[sectionKey],
        content,
        edited: true,
        status: content.trim() ? 'done' : 'idle',
        updatedAt: nowIso(),
      }
      return {
        ...draft,
        sections: { ...draft.sections, [sectionKey]: nextSection },
      }
    }),
  }
}

export function toggleDraftSectionLock(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections']
): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  return {
    ...session,
    drafts: session.drafts.map((draft) => {
      if (draft.questionId !== targetId) return draft
      const nextSection = {
        ...draft.sections[sectionKey],
        locked: !draft.sections[sectionKey].locked,
      }
      return {
        ...draft,
        sections: { ...draft.sections, [sectionKey]: nextSection },
      }
    }),
  }
}

export function markDraftSectionRegenerating(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections']
): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  return {
    ...session,
    drafts: session.drafts.map((draft) => {
      if (draft.questionId !== targetId) return draft
      const nextSection = {
        ...draft.sections[sectionKey],
        status: 'streaming' as const,
        updatedAt: nowIso(),
      }
      return {
        ...draft,
        status: 'streaming',
        sections: { ...draft.sections, [sectionKey]: nextSection },
      }
    }),
  }
}

export function finalizeDraftSectionRegeneration(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections']
): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  return {
    ...session,
    drafts: session.drafts.map((draft) => {
      if (draft.questionId !== targetId) return draft
      const nextSection = {
        ...draft.sections[sectionKey],
        status: draft.sections[sectionKey].content.trim() ? 'done' as const : 'idle' as const,
        updatedAt: nowIso(),
      }
      return {
        ...draft,
        status: 'ready',
        sections: { ...draft.sections, [sectionKey]: nextSection },
      }
    }),
  }
}

export function applyRegeneratedDraftSection(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections'],
  content: string
): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  return {
    ...session,
    drafts: session.drafts.map((draft) => {
      if (draft.questionId !== targetId) return draft
      const nextSection = {
        ...draft.sections[sectionKey],
        content,
        status: content.trim() ? ('done' as const) : ('idle' as const),
        updatedAt: nowIso(),
        edited: false,
      }
      return {
        ...draft,
        status: 'ready',
        sections: { ...draft.sections, [sectionKey]: nextSection },
      }
    }),
  }
}

export function failDraftSectionRegeneration(
  session: AiGenerateStudioSession,
  questionId: string,
  sectionKey: keyof AiGenerateDraftCard['sections']
): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  return {
    ...session,
    drafts: session.drafts.map((draft) => {
      if (draft.questionId !== targetId) return draft
      const nextSection = {
        ...draft.sections[sectionKey],
        status: 'failed' as const,
        updatedAt: nowIso(),
      }
      return {
        ...draft,
        status: 'failed',
        sections: { ...draft.sections, [sectionKey]: nextSection },
      }
    }),
  }
}

export function toggleDraftConfirmed(session: AiGenerateStudioSession, questionId: string): AiGenerateStudioSession {
  const targetId = String(questionId || '').trim()
  const has = session.confirmedIds.includes(targetId)
  return {
    ...session,
    confirmedIds: has
      ? session.confirmedIds.filter((item) => item !== targetId)
      : [...session.confirmedIds, targetId],
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
  }))
}
