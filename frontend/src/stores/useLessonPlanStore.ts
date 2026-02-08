import { create } from 'zustand'
import { persist } from 'zustand/middleware'
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
          plansById: { ...state.plansById, [plan.id]: plan },
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
      partialize: (state) => ({ plansById: state.plansById }),
    }
  )
)

