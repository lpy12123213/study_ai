import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type QuestionBarSourceMode = 'local' | 'zujuan'

export type QuestionBarItem = {
  questionId: string
  origin?: string
  stem?: string
  sourceUrl?: string
}

type AddResult = { ok: true } | { ok: false; error: string }

interface QuestionBarState {
  sourceMode: QuestionBarSourceMode | null
  items: QuestionBarItem[]
  addItem: (item: QuestionBarItem) => AddResult
  removeItem: (questionId: string) => void
  clear: () => void
}

function inferMode(item: QuestionBarItem): QuestionBarSourceMode {
  const origin = String(item.origin || '').trim().toLowerCase()
  const qid = String(item.questionId || '').trim()
  if (origin === 'crawled' && /^\d+$/.test(qid)) return 'zujuan'
  return 'local'
}

const MAX_ITEMS = 200

export const useQuestionBarStore = create<QuestionBarState>()(
  persist(
    (set, get) => ({
      sourceMode: null,
      items: [],
      addItem: (input) => {
        const item: QuestionBarItem = {
          questionId: String(input?.questionId || '').trim(),
          origin: typeof input?.origin === 'string' ? input.origin : undefined,
          stem: typeof input?.stem === 'string' ? input.stem : undefined,
          sourceUrl: typeof input?.sourceUrl === 'string' ? input.sourceUrl : undefined,
        }

        if (!item.questionId) return { ok: false, error: 'missing_question_id' }
        const mode = inferMode(item)
        const state = get()

        if (state.items.length === 0) {
          set({ sourceMode: mode, items: [item] })
          return { ok: true }
        }

        if (state.sourceMode && state.sourceMode !== mode) {
          return {
            ok: false,
            error:
              state.sourceMode === 'zujuan'
                ? '当前试题栏为组卷网模式，不能加入本地/AI 题'
                : '当前试题栏为本地模式，不能加入组卷网题',
          }
        }

        if (state.items.some((x) => x.questionId === item.questionId)) return { ok: true }

        set((prev) => ({
          sourceMode: prev.sourceMode || mode,
          items: [item, ...prev.items].slice(0, MAX_ITEMS),
        }))
        return { ok: true }
      },
      removeItem: (questionId) => {
        const qid = String(questionId || '').trim()
        if (!qid) return
        set((state) => {
          const next = state.items.filter((x) => x.questionId !== qid)
          return { items: next, sourceMode: next.length === 0 ? null : state.sourceMode }
        })
      },
      clear: () => set({ items: [], sourceMode: null }),
    }),
    { name: 'question_bar' }
  )
)

