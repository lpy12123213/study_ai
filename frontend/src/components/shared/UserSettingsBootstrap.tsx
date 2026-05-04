import { useEffect } from 'react'
import { useAuthStore } from '@/stores/useAuthStore'
import { bindSystemThemeListener, useThemeStore } from '@/stores/useThemeStore'
import { useUiPreferencesStore, type UiContrast, type UiDensity } from '@/stores/useUiPreferencesStore'
import { useUserSettingsStore } from '@/stores/useUserSettingsStore'
import {
  useAppearanceStore,
  isDesignStylePreset,
  type AppearancePreferences,
  type ContentLayout,
  type DesignStylePreset,
  type SidebarPosition,
  type SidebarStyle,
} from '@/stores/useAppearanceStore'

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
    const cleanupThemeListener = bindSystemThemeListener()
    useThemeStore.getState().syncTheme()
    useAppearanceStore.getState().applyAppearance()

    return () => {
      cleanupThemeListener?.()
    }
  }, [])

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

        const uiPatch: {
          fontScale?: number
          lineHeight?: number
          density?: UiDensity
          contrast?: UiContrast
          reduceMotion?: boolean
        } = {
          ...(fontScale != null ? { fontScale } : {}),
          ...(lineHeight != null ? { lineHeight } : {}),
          ...(density === 'comfortable' || density === 'compact' ? { density } : {}),
          ...(contrast === 'normal' || contrast === 'high' || contrast === 'eye' ? { contrast } : {}),
          ...(reduceMotion != null ? { reduceMotion } : {}),
        }
        useUiPreferencesStore.getState().setPreferences(uiPatch)
      }

      const appearanceObj = settings.appearance
      if (isPlainObject(appearanceObj)) {
        const sidebarStyle = String(appearanceObj.sidebarStyle || '').trim()
        const contentLayout = String(appearanceObj.contentLayout || '').trim()
        const sidebarPosition = String(appearanceObj.sidebarPosition || '').trim()
        const designStyle = String(appearanceObj.designStyle || '').trim()

        const appearancePatch: Partial<AppearancePreferences> = {
          ...(isDesignStylePreset(designStyle) ? { designStyle: designStyle as DesignStylePreset } : {}),
          ...(sidebarStyle === 'inset' || sidebarStyle === 'floating' || sidebarStyle === 'sidebar'
            ? { sidebarStyle: sidebarStyle as SidebarStyle }
            : {}),
          ...(contentLayout === 'default' || contentLayout === 'compact' || contentLayout === 'full'
            ? { contentLayout: contentLayout as ContentLayout }
            : {}),
          ...(sidebarPosition === 'left' || sidebarPosition === 'right'
            ? { sidebarPosition: sidebarPosition as SidebarPosition }
            : {}),
        }
        useAppearanceStore.getState().setAppearance(appearancePatch)
      }

      const sidebarObj = settings.sidebar
      if (isPlainObject(sidebarObj)) {
        const collapsed = toOptionalBoolean(sidebarObj.collapsed)
        if (collapsed != null) {
          useAppearanceStore.getState().setAppearance({ sidebarCollapsed: collapsed })
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

