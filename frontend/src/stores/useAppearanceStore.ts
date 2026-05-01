import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type SidebarStyle = 'inset' | 'floating' | 'sidebar'
export type ContentLayout = 'default' | 'compact' | 'full'
export type SidebarPosition = 'left' | 'right'

export type AppearancePreferences = {
  sidebarStyle: SidebarStyle
  contentLayout: ContentLayout
  sidebarPosition: SidebarPosition
}

interface AppearanceState extends AppearancePreferences {
  setAppearance: (patch: Partial<AppearancePreferences>) => void
  applyAppearance: () => void
  resetAppearance: () => void
}

const DEFAULTS: AppearancePreferences = {
  sidebarStyle: 'sidebar',
  contentLayout: 'default',
  sidebarPosition: 'left',
}

function normalizeSidebarStyle(value: unknown): SidebarStyle {
  return value === 'inset' || value === 'floating' || value === 'sidebar' ? value : DEFAULTS.sidebarStyle
}

function normalizeContentLayout(value: unknown): ContentLayout {
  return value === 'default' || value === 'compact' || value === 'full' ? value : DEFAULTS.contentLayout
}

function normalizeSidebarPosition(value: unknown): SidebarPosition {
  return value === 'right' ? 'right' : 'left'
}

function applyToDom(prefs: AppearancePreferences) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.sidebarStyle = prefs.sidebarStyle
  root.dataset.contentLayout = prefs.contentLayout
  root.dataset.sidebarPosition = prefs.sidebarPosition
}

export const useAppearanceStore = create<AppearanceState>()(
  persist(
    (set, get) => {
      const applyAppearance = () => {
        const { sidebarStyle, contentLayout, sidebarPosition } = get()
        applyToDom({ sidebarStyle, contentLayout, sidebarPosition })
      }

      applyToDom(DEFAULTS)

      return {
        ...DEFAULTS,
        setAppearance: (patch) => {
          set((state) => ({
            sidebarStyle:
              patch.sidebarStyle !== undefined ? normalizeSidebarStyle(patch.sidebarStyle) : state.sidebarStyle,
            contentLayout:
              patch.contentLayout !== undefined ? normalizeContentLayout(patch.contentLayout) : state.contentLayout,
            sidebarPosition:
              patch.sidebarPosition !== undefined
                ? normalizeSidebarPosition(patch.sidebarPosition)
                : state.sidebarPosition,
          }))
          applyAppearance()
        },
        applyAppearance,
        resetAppearance: () => {
          set({ ...DEFAULTS })
          applyToDom(DEFAULTS)
        },
      }
    },
    {
      name: 'appearance-preferences',
      partialize: (state) => ({
        sidebarStyle: state.sidebarStyle,
        contentLayout: state.contentLayout,
        sidebarPosition: state.sidebarPosition,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) state.applyAppearance()
      },
    },
  ),
)
