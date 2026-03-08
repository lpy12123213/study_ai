import { create } from 'zustand'
import * as userSettingsApi from '@/api/userSettings'

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function deepMerge(base: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base }
  for (const [k, v] of Object.entries(patch)) {
    if (isPlainObject(v) && isPlainObject(out[k])) {
      out[k] = deepMerge(out[k] as Record<string, unknown>, v)
      continue
    }
    out[k] = v
  }
  return out
}

interface UserSettingsState {
  loaded: boolean
  isLoading: boolean
  isSaving: boolean
  error: string | null
  settings: Record<string, unknown>
  loadFromServer: () => Promise<void>
  patchLocal: (patch: Record<string, unknown>) => void
  saveToServer: () => Promise<void>
  patchAndSave: (patch: Record<string, unknown>) => Promise<void>
  exportFromServer: () => Promise<Record<string, unknown>>
  importToServer: (settings: Record<string, unknown>) => Promise<void>
  resetToDefaults: () => Promise<void>
}

export const useUserSettingsStore = create<UserSettingsState>()((set, get) => ({
  loaded: false,
  isLoading: false,
  isSaving: false,
  error: null,
  settings: {},

  loadFromServer: async () => {
    if (get().isLoading) return
    set({ isLoading: true, error: null })
    try {
      const res = await userSettingsApi.getUserSettings()
      const settings = isPlainObject((res as any)?.settings) ? ((res as any).settings as Record<string, unknown>) : {}
      set({ loaded: true, settings })
    } catch (e) {
      set({ error: (e as any)?.message ? String((e as any).message) : 'load_failed' })
    } finally {
      set({ isLoading: false })
    }
  },

  patchLocal: (patch) => {
    const base = get().settings
    set({ settings: deepMerge(base, patch) })
  },

  saveToServer: async () => {
    if (get().isSaving) return
    set({ isSaving: true, error: null })
    try {
      const saved = await userSettingsApi.putUserSettings(get().settings)
      const next = isPlainObject((saved as any)?.settings) ? ((saved as any).settings as Record<string, unknown>) : {}
      set({ settings: next, loaded: true })
    } catch (e) {
      set({ error: (e as any)?.message ? String((e as any).message) : 'save_failed' })
      throw e
    } finally {
      set({ isSaving: false })
    }
  },

  patchAndSave: async (patch) => {
    get().patchLocal(patch)
    await get().saveToServer()
  },

  exportFromServer: async () => {
    const res = await userSettingsApi.exportUserSettings()
    const settings = isPlainObject((res as any)?.settings) ? ((res as any).settings as Record<string, unknown>) : {}
    return settings
  },

  importToServer: async (settings) => {
    const payload = isPlainObject(settings) ? settings : {}
    const res = await userSettingsApi.importUserSettings(payload)
    const next = isPlainObject((res as any)?.settings) ? ((res as any).settings as Record<string, unknown>) : {}
    set({ settings: next, loaded: true })
  },

  resetToDefaults: async () => {
    const res = await userSettingsApi.putUserSettings({})
    const next = isPlainObject((res as any)?.settings) ? ((res as any).settings as Record<string, unknown>) : {}
    set({ settings: next, loaded: true })
  },
}))

