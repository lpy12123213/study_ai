import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { APPEARANCE_PREFERENCES_STORAGE_KEY, SIDEBAR_COLLAPSED_STORAGE_KEY } from '@/constants/storage'

export type SidebarStyle = 'inset' | 'floating' | 'sidebar'
export type ContentLayout = 'default' | 'compact' | 'full'
export type SidebarPosition = 'left' | 'right'
export type DesignStylePreset =
  | 'cursor'
  | 'linear'
  | 'vercel'
  | 'notion'
  | 'supabase'
  | 'voltagent'
  | 'claude'
  | 'stripe'

export type DesignStylePresetMeta = {
  value: DesignStylePreset
  label: string
  source: string
  description: string
  background: string
  surface: string
  foreground: string
  accent: string
}

export const DESIGN_STYLE_PRESETS: DesignStylePresetMeta[] = [
  {
    value: 'cursor',
    label: 'Cursor Editorial',
    source: 'design.md',
    description: 'Warm cream canvas, sparse orange action, editorial product calm.',
    background: '#f7f7f4',
    surface: '#ffffff',
    foreground: '#26251e',
    accent: '#f54e00',
  },
  {
    value: 'linear',
    label: 'Linear',
    source: 'awesome-design-md/design-md/linear.app',
    description: 'Near-black product surface, lavender-blue accent, precise hairlines.',
    background: '#010102',
    surface: '#0f1011',
    foreground: '#f7f8f8',
    accent: '#5e6ad2',
  },
  {
    value: 'vercel',
    label: 'Vercel',
    source: 'awesome-design-md/design-md/vercel',
    description: 'Monochrome precision, white panels, black primary action.',
    background: '#fafafa',
    surface: '#ffffff',
    foreground: '#000000',
    accent: '#000000',
  },
  {
    value: 'notion',
    label: 'Notion',
    source: 'awesome-design-md/design-md/notion',
    description: 'Warm workspace minimalism, soft surfaces, restrained ink controls.',
    background: '#f7f6f3',
    surface: '#ffffff',
    foreground: '#2f3437',
    accent: '#2f3437',
  },
  {
    value: 'supabase',
    label: 'Supabase',
    source: 'awesome-design-md/design-md/supabase',
    description: 'Dark developer console, emerald accent, code-first contrast.',
    background: '#0b0f0e',
    surface: '#111716',
    foreground: '#f1f5f3',
    accent: '#3ecf8e',
  },
  {
    value: 'voltagent',
    label: 'VoltAgent',
    source: 'awesome-design-md/design-md/voltagent',
    description: 'Void-black terminal-native agent UI with electric emerald actions.',
    background: '#030705',
    surface: '#0b120f',
    foreground: '#eefcf5',
    accent: '#00d084',
  },
  {
    value: 'claude',
    label: 'Claude',
    source: 'awesome-design-md/design-md/claude',
    description: 'Clean editorial layout with warm terracotta accent and soft panels.',
    background: '#f8f4ed',
    surface: '#fffdf8',
    foreground: '#2b2118',
    accent: '#c15f3c',
  },
  {
    value: 'stripe',
    label: 'Stripe',
    source: 'awesome-design-md/design-md/stripe',
    description: 'Airy finance-grade canvas, purple action color, crisp blue-gray panels.',
    background: '#f6f9fc',
    surface: '#ffffff',
    foreground: '#0a2540',
    accent: '#635bff',
  },
]

export type AppearancePreferences = {
  designStyle: DesignStylePreset
  sidebarStyle: SidebarStyle
  sidebarCollapsed: boolean
  contentLayout: ContentLayout
  sidebarPosition: SidebarPosition
}

interface AppearanceState extends AppearancePreferences {
  setAppearance: (patch: Partial<AppearancePreferences>) => void
  setSidebarCollapsed: (collapsed: boolean) => void
  applyAppearance: () => void
  resetAppearance: () => void
}

function readInitialSidebarCollapsed(): boolean {
  if (typeof window === 'undefined') return false

  try {
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)
    if (stored === 'true') return true
    if (stored === 'false') return false
  } catch {
    // ignore
  }

  return window.matchMedia('(max-width: 767px)').matches
}

const DEFAULTS: AppearancePreferences = {
  designStyle: 'cursor',
  sidebarStyle: 'sidebar',
  sidebarCollapsed: readInitialSidebarCollapsed(),
  contentLayout: 'default',
  sidebarPosition: 'left',
}

export function isDesignStylePreset(value: unknown): value is DesignStylePreset {
  return DESIGN_STYLE_PRESETS.some((preset) => preset.value === value)
}

function normalizeDesignStyle(value: unknown): DesignStylePreset {
  return isDesignStylePreset(value) ? value : DEFAULTS.designStyle
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

export function applyAppearancePreferences(prefs: AppearancePreferences) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.designStyle = prefs.designStyle
  root.dataset.sidebarStyle = prefs.sidebarStyle
  root.dataset.sidebarCollapsed = prefs.sidebarCollapsed ? 'true' : 'false'
  root.dataset.contentLayout = prefs.contentLayout
  root.dataset.sidebarPosition = prefs.sidebarPosition
}

export const useAppearanceStore = create<AppearanceState>()(
  persist(
    (set, get) => {
      const applyAppearance = () => {
        const { designStyle, sidebarStyle, sidebarCollapsed, contentLayout, sidebarPosition } = get()
        applyAppearancePreferences({ designStyle, sidebarStyle, sidebarCollapsed, contentLayout, sidebarPosition })
      }

      return {
        ...DEFAULTS,
        setAppearance: (patch) => {
          set((state) => ({
            designStyle:
              patch.designStyle !== undefined ? normalizeDesignStyle(patch.designStyle) : state.designStyle,
            sidebarStyle:
              patch.sidebarStyle !== undefined ? normalizeSidebarStyle(patch.sidebarStyle) : state.sidebarStyle,
            sidebarCollapsed:
              patch.sidebarCollapsed !== undefined ? Boolean(patch.sidebarCollapsed) : state.sidebarCollapsed,
            contentLayout:
              patch.contentLayout !== undefined ? normalizeContentLayout(patch.contentLayout) : state.contentLayout,
            sidebarPosition:
              patch.sidebarPosition !== undefined
                ? normalizeSidebarPosition(patch.sidebarPosition)
                : state.sidebarPosition,
          }))
          applyAppearance()
        },
        setSidebarCollapsed: (collapsed) => {
          set({ sidebarCollapsed: Boolean(collapsed) })
          applyAppearance()
        },
        applyAppearance,
        resetAppearance: () => {
          set({ ...DEFAULTS })
          applyAppearancePreferences(DEFAULTS)
        },
      }
    },
    {
      name: APPEARANCE_PREFERENCES_STORAGE_KEY,
      partialize: (state) => ({
        sidebarStyle: state.sidebarStyle,
        sidebarCollapsed: state.sidebarCollapsed,
        contentLayout: state.contentLayout,
        sidebarPosition: state.sidebarPosition,
        designStyle: state.designStyle,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) state.applyAppearance()
      },
    },
  ),
)
