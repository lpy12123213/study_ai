import { create } from 'zustand'
import type { ExamQuestion, SaveExamAnswerRequest } from '@/types/exam'

type TimerColor = 'green' | 'yellow' | 'red'

interface ExamState {
  sessionId: string
  questions: ExamQuestion[]
  currentQuestionIndex: number
  answers: Record<string, SaveExamAnswerRequest>
  dirtyQuestionIds: string[]
  remainingSeconds: number | null
  timerColor: TimerColor
  lastSavedAt: string
  isSaving: boolean
  setSession: (sessionId: string, questions: ExamQuestion[], expiresAt?: string | null) => void
  setCurrentQuestionIndex: (index: number) => void
  updateAnswer: (questionId: string, data: Partial<SaveExamAnswerRequest>) => void
  markSaved: (questionIds?: string[]) => void
  setSaving: (saving: boolean) => void
  tick: (expiresAt?: string | null) => number | null
  reset: () => void
}

const initialState = {
  sessionId: '',
  questions: [],
  currentQuestionIndex: 0,
  answers: {},
  dirtyQuestionIds: [],
  remainingSeconds: null,
  timerColor: 'green' as TimerColor,
  lastSavedAt: '',
  isSaving: false,
}

function calcRemaining(expiresAt?: string | null): number | null {
  if (!expiresAt) return null
  const ts = Date.parse(expiresAt)
  if (!Number.isFinite(ts)) return null
  return Math.max(0, Math.ceil((ts - Date.now()) / 1000))
}

function timerColor(seconds: number | null): TimerColor {
  if (seconds === null) return 'green'
  if (seconds <= 60) return 'red'
  if (seconds <= 5 * 60) return 'yellow'
  return 'green'
}

export const useExamStore = create<ExamState>((set, get) => ({
  ...initialState,
  setSession: (sessionId, questions, expiresAt) => {
    const remaining = calcRemaining(expiresAt)
    set({
      sessionId,
      questions,
      currentQuestionIndex: 0,
      remainingSeconds: remaining,
      timerColor: timerColor(remaining),
    })
  },
  setCurrentQuestionIndex: (index) => {
    const count = get().questions.length
    set({ currentQuestionIndex: Math.max(0, Math.min(index, Math.max(0, count - 1))) })
  },
  updateAnswer: (questionId, data) => {
    const qid = String(questionId || '').trim()
    if (!qid) return
    set((state) => {
      const prev = state.answers[qid] ?? { questionId: qid }
      const dirty = state.dirtyQuestionIds.includes(qid) ? state.dirtyQuestionIds : [...state.dirtyQuestionIds, qid]
      return {
        answers: {
          ...state.answers,
          [qid]: { ...prev, ...data, questionId: qid },
        },
        dirtyQuestionIds: dirty,
      }
    })
  },
  markSaved: (questionIds) => {
    const ids = new Set((questionIds || get().dirtyQuestionIds).map((id) => String(id)))
    set((state) => ({
      dirtyQuestionIds: state.dirtyQuestionIds.filter((id) => !ids.has(id)),
      lastSavedAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }))
  },
  setSaving: (saving) => set({ isSaving: saving }),
  tick: (expiresAt) => {
    const remaining = calcRemaining(expiresAt)
    set({ remainingSeconds: remaining, timerColor: timerColor(remaining) })
    return remaining
  },
  reset: () => set({ ...initialState }),
}))
