import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { sanitizeLessonPlan } from '@/lib/taskPayload'
import type { LessonPlan } from '@/types'

interface LessonPlanStoreState {
  plansById: Record<string, LessonPlan>

  savePlan: (plan: LessonPlan) => void
  removePlan: (id: string) => void
  getPlan: (id: string) => LessonPlan | undefined
}

export const useLessonPlanStore = create<LessonPlanStoreState>()(
  persist(
    (set, get) => ({
      plansById: {},

      savePlan: (plan) =>
        set((state) => ({
          plansById: { ...state.plansById, [plan.id]: sanitizeLessonPlan(plan) },
        })),

      removePlan: (id) =>
        set((state) => {
          const next = { ...state.plansById }
          delete next[id]
          return { plansById: next }
        }),

      getPlan: (id) => get().plansById[id],
    }),
    {
      name: 'lesson-plan-storage',
      version: 2,
      migrate: (persistedState: unknown) => {
        const state = (persistedState || {}) as Partial<LessonPlanStoreState>
        const rawPlans = state.plansById && typeof state.plansById === 'object' ? state.plansById : {}
        const plansById = Object.fromEntries(
          Object.entries(rawPlans as Record<string, LessonPlan>).map(([id, plan]) => [id, sanitizeLessonPlan(plan)])
        ) as Record<string, LessonPlan>
        return { ...state, plansById } as LessonPlanStoreState
      },
      partialize: (state) => ({
        plansById: Object.fromEntries(
          Object.entries(state.plansById || {}).map(([id, plan]) => [id, sanitizeLessonPlan(plan)])
        ) as Record<string, LessonPlan>,
      }),
    }
  )
)

