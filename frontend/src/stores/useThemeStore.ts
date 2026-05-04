import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type ThemeMode = 'light' | 'dark' | 'system'
type ResolvedTheme = 'light' | 'dark'

interface ThemeState {
  theme: ThemeMode
  resolvedTheme: ResolvedTheme
  setTheme: (theme: ThemeMode) => void
  toggleTheme: () => void
  syncTheme: () => void
}

function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'light'
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function resolveTheme(mode: ThemeMode): ResolvedTheme {
  return mode === 'system' ? getSystemTheme() : mode
}

function applyResolvedTheme(theme: ResolvedTheme) {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', theme === 'dark')
  // Improve native form controls / scrollbar color rendering.
  if (document.documentElement.style.colorScheme !== theme) {
    document.documentElement.style.colorScheme = theme
  }
}

export function bindSystemThemeListener() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  const store = useThemeStore

  const mql = window.matchMedia('(prefers-color-scheme: dark)')
  const onChange = () => {
    const state = store.getState()
    if (state.theme !== 'system') return
    const next = getSystemTheme()
    if (next === state.resolvedTheme) return
    store.setState({ resolvedTheme: next })
    applyResolvedTheme(next)
  }

  if (typeof mql.addEventListener === 'function') {
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  } else {
    // Safari < 14
    mql.addListener(onChange)
    return () => mql.removeListener(onChange)
  }
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => {
      const syncTheme = () => {
        const state = get()
        const resolved = resolveTheme(state.theme)
        if (resolved !== state.resolvedTheme) {
          set({ resolvedTheme: resolved })
        }
        applyResolvedTheme(resolved)
      }

      const initialMode: ThemeMode = 'system'
      const initialResolved = resolveTheme(initialMode)

      return {
        theme: initialMode,
        resolvedTheme: initialResolved,
        setTheme: (theme) => {
          const resolved = resolveTheme(theme)
          set({ theme, resolvedTheme: resolved })
          applyResolvedTheme(resolved)
        },
        toggleTheme: () => {
          const cur = get().theme
          const next: ThemeMode =
            cur === 'system' ? 'light' : cur === 'light' ? 'dark' : 'system'
          const resolved = resolveTheme(next)
          set({ theme: next, resolvedTheme: resolved })
          applyResolvedTheme(resolved)
        },
        syncTheme,
      }
    },
    {
      name: 'theme-storage',
      partialize: (state) => ({ theme: state.theme }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.syncTheme()
        }
      },
    }
  )
)
