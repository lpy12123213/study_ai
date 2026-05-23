import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '@/stores/useAuthStore'
import { useThemeStore } from '@/stores/useThemeStore'
import { useUiPreferencesStore } from '@/stores/useUiPreferencesStore'
import { useUserSettingsStore } from '@/stores/useUserSettingsStore'
import {
  useAppearanceStore,
  type AppearancePreferences,
} from '@/stores/useAppearanceStore'
import { SettingsSidebar, type SettingsTabId } from '@/features/settings/components/SettingsSidebar'
import { AccountPanel } from '@/features/settings/components/AccountPanel'
import { ApiSettingsPanel } from '@/features/settings/components/ApiSettingsPanel'
import { AppearancePanel } from '@/features/settings/components/AppearancePanel'
import { DataPanel } from '@/features/settings/components/DataPanel'
import { AboutPanel } from '@/features/settings/components/AboutPanel'
import { useApiSettings } from '@/features/settings/hooks/useApiSettings'

export default function SettingsView() {
  const [activeTab, setActiveTab] = useState<SettingsTabId>('account')
  const { user, isAuthenticated } = useAuthStore()
  const { theme, setTheme } = useThemeStore()
  const { fontScale, lineHeight, density, contrast, reduceMotion, setPreferences, resetPreferences } =
    useUiPreferencesStore()
  const {
    designStyle,
    sidebarStyle,
    contentLayout,
    sidebarPosition,
    setAppearance,
    resetAppearance,
  } = useAppearanceStore()
  const {
    loaded: userSettingsLoaded,
    loadFromServer,
    patchLocal,
    saveToServer,
    exportFromServer,
    importToServer,
    resetToDefaults,
    isSaving: isSyncing,
    error: syncError,
  } = useUserSettingsStore()

  const syncTimerRef = useRef<number | null>(null)

  const scheduleAccountSave = (patch: Record<string, unknown>) => {
    if (!isAuthenticated) return
    patchLocal(patch)
    if (syncTimerRef.current) window.clearTimeout(syncTimerRef.current)
    syncTimerRef.current = window.setTimeout(() => {
      void saveToServer()
    }, 800)
  }

  useEffect(() => {
    if (!isAuthenticated) return
    if (userSettingsLoaded) return
    void loadFromServer()
  }, [isAuthenticated, loadFromServer, userSettingsLoaded])

  useEffect(() => {
    return () => {
      if (syncTimerRef.current) window.clearTimeout(syncTimerRef.current)
    }
  }, [])

  const api = useApiSettings()

  const updateAppearance = (patch: Partial<AppearancePreferences>) => {
    setAppearance(patch)
    scheduleAccountSave({ appearance: patch })
  }

  return (
    <div className="h-full flex flex-col md:flex-row overflow-hidden bg-background">
      <SettingsSidebar activeTab={activeTab} onSelectTab={setActiveTab} />

      <main className="flex-1 overflow-auto p-6 md:p-10">
        <div className="max-w-2xl mx-auto space-y-8">
          {activeTab === 'account' && <AccountPanel user={user} />}

          {activeTab === 'api' && <ApiSettingsPanel api={api} isActive={activeTab === 'api'} />}

          {activeTab === 'appearance' && (
            <AppearancePanel
              theme={theme}
              setTheme={setTheme}
              designStyle={designStyle}
              sidebarStyle={sidebarStyle}
              contentLayout={contentLayout}
              sidebarPosition={sidebarPosition}
              fontScale={fontScale}
              lineHeight={lineHeight}
              density={density}
              contrast={contrast}
              reduceMotion={reduceMotion}
              isAuthenticated={isAuthenticated}
              isSyncing={isSyncing}
              syncError={syncError}
              resetAppearance={resetAppearance}
              resetPreferences={resetPreferences}
              updateAppearance={updateAppearance}
              setPreferences={setPreferences}
              scheduleAccountSave={scheduleAccountSave}
            />
          )}

          {activeTab === 'data' && (
            <DataPanel
              isAuthenticated={isAuthenticated}
              exportFromServer={exportFromServer}
              importToServer={importToServer}
              resetToDefaults={resetToDefaults}
              setTheme={setTheme}
              setPreferences={setPreferences}
              resetPreferences={resetPreferences}
              setAppearance={setAppearance}
              resetAppearance={resetAppearance}
            />
          )}

          {activeTab === 'about' && <AboutPanel />}
        </div>
      </main>
    </div>
  )
}
