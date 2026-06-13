import { useEffect, useRef, useState } from 'react'
import { Sparkles } from 'lucide-react'
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
import { LlmDebugPanel } from '@/features/settings/components/LlmDebugPanel'
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

  const flushAccountSave = () => {
    if (!syncTimerRef.current) return
    window.clearTimeout(syncTimerRef.current)
    syncTimerRef.current = null
    void saveToServer()
  }

  const scheduleAccountSave = (patch: Record<string, unknown>) => {
    if (!isAuthenticated) return
    patchLocal(patch)
    if (syncTimerRef.current) window.clearTimeout(syncTimerRef.current)
    syncTimerRef.current = window.setTimeout(() => {
      syncTimerRef.current = null
      void saveToServer()
    }, 800)
  }

  useEffect(() => {
    if (!isAuthenticated) return
    if (userSettingsLoaded) return
    void loadFromServer()
  }, [isAuthenticated, loadFromServer, userSettingsLoaded])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') flushAccountSave()
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      flushAccountSave()
    }
  }, [saveToServer])

  const api = useApiSettings()

  const updateAppearance = (patch: Partial<AppearancePreferences>) => {
    setAppearance(patch)
    scheduleAccountSave({ appearance: patch })
  }
  const settingsStats = [
    { label: '当前页', value: activeTab },
    { label: '主题', value: theme },
    { label: '登录', value: isAuthenticated ? '已连接' : '本地模式' },
    { label: '同步', value: isSyncing ? '保存中' : syncError ? '异常' : '就绪' },
  ]

  return (
    <div className="aurora-settings-screen h-full flex flex-col md:flex-row overflow-hidden">
      <SettingsSidebar activeTab={activeTab} onSelectTab={setActiveTab} />

      <main className="flex-1 overflow-auto p-6 md:p-10">
        <div className="max-w-3xl mx-auto space-y-8">
          <section className="aurora-settings-hero">
            <div>
              <div className="aurora-kicker">
                <Sparkles className="h-3.5 w-3.5" />
                System Settings Console
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight">系统设置控制台</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                管理账户、本地偏好、模型连接、外观方案、数据导入导出与调试状态。
              </p>
            </div>
            <div className="aurora-settings-stat-grid">
              {settingsStats.map((item) => (
                <div key={item.label} className="aurora-settings-stat">
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>
          </section>

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

          {activeTab === 'debug' && <LlmDebugPanel isActive={activeTab === 'debug'} />}

          {activeTab === 'about' && <AboutPanel />}
        </div>
      </main>
    </div>
  )
}
