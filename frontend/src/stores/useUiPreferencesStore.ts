import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type UiDensity = 'comfortable' | 'compact'
export type UiContrast = 'normal' | 'high' | 'eye'

export type UiPreferences = {
  fontScale: number
  lineHeight: number
  density: UiDensity
  contrast: UiContrast
  reduceMotion: boolean
}

interface UiPreferencesState extends UiPreferences {
  setPreferences: (patch: Partial<UiPreferences>) => void
  applyPreferences: () => void
  resetPreferences: () => void
}

function clamp(n: number, min: number, max: number): number {
  if (!Number.isFinite(n)) return min
  return Math.max(min, Math.min(max, n))
}

function applyToDom(p: UiPreferences) {
  if (typeof document === 'undefined') return
  const root = document.documentElement

  const density = p.density === 'compact' ? 'compact' : 'comfortable'
  root.dataset.density = density

  const contrast = p.contrast === 'high' ? 'high' : p.contrast === 'eye' ? 'eye' : 'normal'
  root.classList.toggle('contrast-high', contrast === 'high')
  root.classList.toggle('contrast-eye', contrast === 'eye')

  root.classList.toggle('reduce-motion', Boolean(p.reduceMotion))

  const fontScale = clamp(Number(p.fontScale || 1), 0.85, 1.25)
  root.style.fontSize = `${Math.round(16 * fontScale * 10) / 10}px`

  const lineHeight = clamp(Number(p.lineHeight || 1.6), 1.2, 2.2)
  root.style.setProperty('--app-line-height', String(lineHeight))
}

const DEFAULTS: UiPreferences = {
  fontScale: 1,
  lineHeight: 1.6,
  density: 'comfortable',
  contrast: 'normal',
  reduceMotion: false,
}

export const useUiPreferencesStore = create<UiPreferencesState>()(
  persist(
    (set, get) => {
      const applyPreferences = () => {
        const { fontScale, lineHeight, density, contrast, reduceMotion } = get()
        applyToDom({ fontScale, lineHeight, density, contrast, reduceMotion })
      }

      // Apply defaults immediately (before rehydrate).
      applyToDom(DEFAULTS)

      return {
        ...DEFAULTS,
        setPreferences: (patch) => {
          set((state) => {
            const next: UiPreferences = {
              fontScale: patch.fontScale !== undefined ? clamp(Number(patch.fontScale), 0.85, 1.25) : state.fontScale,
              lineHeight: patch.lineHeight !== undefined ? clamp(Number(patch.lineHeight), 1.2, 2.2) : state.lineHeight,
              density: patch.density ?? state.density,
              contrast: patch.contrast ?? state.contrast,
              reduceMotion: patch.reduceMotion ?? state.reduceMotion,
            }
            return next
          })
          applyPreferences()
        },
        applyPreferences,
        resetPreferences: () => {
          set({ ...DEFAULTS })
          applyToDom(DEFAULTS)
        },
      }
    },
    {
      name: 'ui-preferences',
      partialize: (state) => ({
        fontScale: state.fontScale,
        lineHeight: state.lineHeight,
        density: state.density,
        contrast: state.contrast,
        reduceMotion: state.reduceMotion,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) state.applyPreferences()
      },
    },
  ),
)

