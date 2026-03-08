import { useEffect } from 'react'
import { useAuthStore } from '@/stores/useAuthStore'
import { useThemeStore } from '@/stores/useThemeStore'
import { useUiPreferencesStore } from '@/stores/useUiPreferencesStore'
import { useUserSettingsStore } from '@/stores/useUserSettingsStore'

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'manus.sidebar.collapsed'

function toOptionalNumber(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
  return Number.isFinite(n) ? n : null
}

function toOptionalBoolean(value: unknown): boolean | null {
  if (value === true) return true
  if (value === false) return false
  if (typeof value === 'string') {
    const v = value.trim().toLowerCase()
    if (v === '1' || v === 'true' || v === 'yes') return true
    if (v === '0' || v === 'false' || v === 'no') return false
  }
  return null
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function UserSettingsBootstrap() {
  const { isAuthenticated, token } = useAuthStore()

  useEffect(() => {
    if (!isAuthenticated || !token) return
    let cancelled = false

    const run = async () => {
      const store = useUserSettingsStore.getState()
      await store.loadFromServer()
      if (cancelled) return

      const settings = store.settings
      if (!isPlainObject(settings)) return

      const themeObj = settings.theme
      if (isPlainObject(themeObj)) {
        const mode = String(themeObj.mode || '').trim()
        if (mode === 'light' || mode === 'dark' || mode === 'system') {
          useThemeStore.getState().setTheme(mode)
        }
      }

      const uiObj = settings.ui
      if (isPlainObject(uiObj)) {
        const fontScale = toOptionalNumber(uiObj.fontScale)
        const lineHeight = toOptionalNumber(uiObj.lineHeight)
        const density = String(uiObj.density || '').trim()
        const contrast = String(uiObj.contrast || '').trim()
        const reduceMotion = toOptionalBoolean(uiObj.reduceMotion)

        useUiPreferencesStore.getState().setPreferences({
          ...(fontScale != null ? { fontScale } : {}),
          ...(lineHeight != null ? { lineHeight } : {}),
          ...(density === 'comfortable' || density === 'compact' ? { density: density as any } : {}),
          ...(contrast === 'normal' || contrast === 'high' || contrast === 'eye' ? { contrast: contrast as any } : {}),
          ...(reduceMotion != null ? { reduceMotion } : {}),
        })
      }

      const sidebarObj = settings.sidebar
      if (isPlainObject(sidebarObj)) {
        const collapsed = toOptionalBoolean(sidebarObj.collapsed)
        if (collapsed != null) {
          try {
            window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, collapsed ? 'true' : 'false')
          } catch {
            // ignore
          }
        }
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [isAuthenticated, token])

  return null
}

