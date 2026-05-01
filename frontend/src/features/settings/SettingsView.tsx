import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Save,
  Loader2,
  Check,
  RefreshCw,
  Eye,
  EyeOff,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { useAuthStore } from '@/stores/useAuthStore'
import { useThemeStore } from '@/stores/useThemeStore'
import { useUiPreferencesStore, type UiContrast, type UiDensity } from '@/stores/useUiPreferencesStore'
import { useUserSettingsStore } from '@/stores/useUserSettingsStore'
import {
  useAppearanceStore,
  type AppearancePreferences,
  type ContentLayout,
  type SidebarPosition,
  type SidebarStyle,
} from '@/stores/useAppearanceStore'
import { cn } from '@/lib/utils'
import { SettingsSidebar, type SettingsTabId } from '@/features/settings/components/SettingsSidebar'
import * as modelSettingsApi from '@/api/modelSettings'
import type { ModelOption, ModelSettingsResponse } from '@/api/modelSettings'

const roleLabels: Record<string, string> = {
  admin: '管理员',
  user: '普通用户',
}

const sidebarOptions: Array<{ value: SidebarStyle; label: string }> = [
  { value: 'inset', label: 'Inset' },
  { value: 'floating', label: 'Floating' },
  { value: 'sidebar', label: 'Sidebar' },
]

const layoutOptions: Array<{ value: ContentLayout; label: string }> = [
  { value: 'default', label: 'Default' },
  { value: 'compact', label: 'Compact' },
  { value: 'full', label: 'Full layout' },
]

const positionOptions: Array<{ value: SidebarPosition; label: string }> = [
  { value: 'left', label: 'Left' },
  { value: 'right', label: 'Right' },
]

type ThemeMode = 'system' | 'light' | 'dark'

const themeOptions: Array<{ value: ThemeMode; label: string }> = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function pickScopedModel(value: unknown, provider: string): string {
  if (typeof value === 'string') return value.trim()
  if (!isRecord(value)) return ''
  const providerValue = value[provider]
  if (typeof providerValue === 'string' && providerValue.trim()) return providerValue.trim()
  const defaultValue = value.default
  if (typeof defaultValue === 'string' && defaultValue.trim()) return defaultValue.trim()
  for (const item of Object.values(value)) {
    if (typeof item === 'string' && item.trim()) return item.trim()
  }
  return ''
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (isRecord(error) && typeof error.message === 'string' && error.message.trim()) return error.message
  return '操作失败'
}

function StyleOptionCard(props: {
  label: string
  selected: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button type="button" className="group block w-full text-left" onClick={props.onClick}>
      <div
        className={cn(
          'relative h-24 rounded-lg border bg-muted/30 p-3 transition-colors',
          props.selected ? 'border-primary ring-2 ring-primary/15' : 'border-border hover:border-primary/50',
        )}
      >
        {props.children}
        {props.selected && (
          <span className="absolute -right-2 -top-2 flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
            <Check className="h-4 w-4" />
          </span>
        )}
      </div>
      <div className="mt-2 text-center text-sm font-medium">{props.label}</div>
    </button>
  )
}

function ThemePreview({ mode }: { mode: 'system' | 'light' | 'dark' }) {
  const dark = mode === 'dark'
  const system = mode === 'system'
  return (
    <div className={cn('h-full rounded-md border overflow-hidden', dark ? 'bg-slate-950' : 'bg-white')}>
      <div className={cn('flex h-full', system && 'opacity-80')}>
        <div className={cn('w-1/3 p-2 space-y-1.5', dark ? 'bg-slate-900' : 'bg-slate-200')}>
          <div className={cn('h-3 w-3 rounded-full', dark ? 'bg-sky-400' : 'bg-white')} />
          <div className={cn('h-1.5 w-8 rounded', dark ? 'bg-sky-500/70' : 'bg-white')} />
          <div className={cn('h-1.5 w-10 rounded', dark ? 'bg-slate-500' : 'bg-slate-400')} />
          <div className={cn('h-1.5 w-7 rounded', dark ? 'bg-slate-500' : 'bg-slate-400')} />
        </div>
        <div className="flex-1 p-3">
          <div className={cn('ml-auto h-8 w-8 rounded-full', dark ? 'bg-blue-950' : 'bg-slate-100')} />
          <div className={cn('mt-2 h-10 rounded', dark ? 'bg-slate-800' : 'bg-slate-100')} />
        </div>
      </div>
    </div>
  )
}

function SidebarPreview({ value }: { value: SidebarStyle }) {
  return (
    <div className="h-full rounded-md border bg-background p-2">
      <div
        className={cn(
          'h-full rounded-md',
          value === 'sidebar' && 'w-1/3 bg-primary/20',
          value === 'inset' && 'ml-1 w-1/3 border bg-primary/10',
          value === 'floating' && 'ml-2 w-1/4 rounded-lg border bg-primary/15 shadow-sm',
        )}
      >
        <div className="space-y-1.5 p-2">
          <div className="h-2 w-2 rounded-full bg-primary/70" />
          <div className="h-1.5 w-8 rounded bg-primary/50" />
          <div className="h-1.5 w-6 rounded bg-muted-foreground/40" />
          <div className="h-1.5 w-7 rounded bg-muted-foreground/40" />
        </div>
      </div>
    </div>
  )
}

function LayoutPreview({ value }: { value: ContentLayout }) {
  const widthClass = value === 'full' ? 'w-full' : value === 'compact' ? 'w-1/2' : 'w-2/3'
  return (
    <div className="h-full rounded-md border bg-background p-2">
      <div className={cn('mx-auto h-full rounded-md bg-primary/15 p-2', widthClass)}>
        <div className="h-2 w-full rounded bg-primary/50" />
        <div className="mt-2 h-8 rounded bg-muted-foreground/25" />
        <div className="mt-2 flex gap-1">
          <div className="h-4 flex-1 rounded bg-muted-foreground/25" />
          <div className="h-4 flex-1 rounded bg-muted-foreground/25" />
        </div>
      </div>
    </div>
  )
}

function PositionPreview({ value }: { value: SidebarPosition }) {
  return (
    <div className={cn('flex h-full rounded-md border bg-background', value === 'right' && 'flex-row-reverse')}>
      <div className="w-1/4 bg-primary/20 p-2">
        <div className="h-2 w-2 rounded-full bg-primary/70" />
        <div className="mt-2 h-1.5 w-8 rounded bg-primary/50" />
        <div className="mt-1 h-1.5 w-6 rounded bg-muted-foreground/40" />
      </div>
      <div className="flex-1 p-3">
        <div className="h-8 rounded bg-muted-foreground/25" />
        <div className="mt-2 h-3 rounded bg-muted-foreground/20" />
      </div>
    </div>
  )
}

export default function SettingsView() {
  const [activeTab, setActiveTab] = useState<SettingsTabId>('account')
  const { user, isAuthenticated } = useAuthStore()
  const { theme, setTheme } = useThemeStore()
  const { fontScale, lineHeight, density, contrast, reduceMotion, setPreferences, resetPreferences } = useUiPreferencesStore()
  const {
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
  const roleLabel = (() => {
    const role = String(user?.role || '').trim().toLowerCase()
    if (!role) return '普通用户'
    return roleLabels[role] || String(user?.role || '普通用户')
  })()

  const [providerName, setProviderName] = useState('openrouter')
  const [providerBaseUrl, setProviderBaseUrl] = useState('https://openrouter.ai/api/v1')
  const [providerApiKey, setProviderApiKey] = useState('')
  const [savedApiKeyMask, setSavedApiKeyMask] = useState('')
  const [savedApiKeyEncrypted, setSavedApiKeyEncrypted] = useState(false)
  const [showProviderApiKey, setShowProviderApiKey] = useState(false)
  const [mainModel, setMainModel] = useState('')
  const [subModel, setSubModel] = useState('')
  const [lessonPlanModel, setLessonPlanModel] = useState('')
  const [providerPinned, setProviderPinned] = useState(true)
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  const [modelSettingsLoaded, setModelSettingsLoaded] = useState(false)
  const [isModelLoading, setIsModelLoading] = useState(false)
  const [isFetchingModels, setIsFetchingModels] = useState(false)
  const [isSavingModelSettings, setIsSavingModelSettings] = useState(false)
  const [modelSettingsMessage, setModelSettingsMessage] = useState('')

  const applyModelSettingsResponse = useCallback((res: ModelSettingsResponse) => {
    const active = String(res.active_provider || '').trim() || 'openrouter'
    const provider = (res.providers || []).find((item) => item.name === active) || (res.providers || [])[0]
    const providerValue = String(provider?.name || active || 'openrouter').trim()

    setProviderName(providerValue)
    setProviderBaseUrl(String(provider?.base_url || '').trim())
    setSavedApiKeyMask(String(provider?.api_key_mask || ''))
    setSavedApiKeyEncrypted(Boolean(provider?.api_key_encrypted))
    setProviderApiKey('')
    setProviderPinned(Boolean(res.pinned))
    setMainModel(pickScopedModel(res.models?.main, providerValue))
    setSubModel(pickScopedModel(res.models?.sub, providerValue))
    setLessonPlanModel(pickScopedModel(res.models?.lesson_plan, providerValue))
  }, [])

  const loadModelSettings = useCallback(async () => {
    setIsModelLoading(true)
    setModelSettingsMessage('')
    try {
      const res = await modelSettingsApi.getModelSettings()
      applyModelSettingsResponse(res)
    } catch (error) {
      setModelSettingsMessage(errorMessage(error))
    } finally {
      setModelSettingsLoaded(true)
      setIsModelLoading(false)
    }
  }, [applyModelSettingsResponse])

  const handleFetchModels = async () => {
    setIsFetchingModels(true)
    setModelSettingsMessage('')
    try {
      const res = await modelSettingsApi.fetchProviderModels({
        provider: providerName.trim(),
        base_url: providerBaseUrl.trim(),
        ...(providerApiKey.trim() ? { api_key: providerApiKey.trim() } : {}),
      })
      setModelOptions(res.models || [])
      const first = res.models?.[0]?.id || ''
      if (first) {
        if (!mainModel.trim()) setMainModel(first)
        if (!subModel.trim()) setSubModel(first)
        if (!lessonPlanModel.trim()) setLessonPlanModel(first)
      }
      setModelSettingsMessage(`已抓取 ${res.count || 0} 个模型`)
    } catch (error) {
      setModelSettingsMessage(errorMessage(error))
    } finally {
      setIsFetchingModels(false)
    }
  }

  const handleSaveModelSettings = async () => {
    setIsSavingModelSettings(true)
    setModelSettingsMessage('')
    try {
      const res = await modelSettingsApi.saveModelSettings({
        active_provider: providerName.trim(),
        pinned: providerPinned,
        provider: {
          name: providerName.trim(),
          base_url: providerBaseUrl.trim(),
          ...(providerApiKey.trim() ? { api_key: providerApiKey.trim() } : {}),
        },
        models: {
          main: mainModel.trim(),
          sub: subModel.trim(),
          lesson_plan: lessonPlanModel.trim(),
        },
      })
      applyModelSettingsResponse(res)
      setModelSettingsLoaded(true)
      setModelSettingsMessage('已加密保存并刷新运行配置')
    } catch (error) {
      setModelSettingsMessage(errorMessage(error))
    } finally {
      setIsSavingModelSettings(false)
    }
  }

  useEffect(() => {
    if (activeTab !== 'api') return
    if (modelSettingsLoaded || isModelLoading) return
    void loadModelSettings()
  }, [activeTab, isModelLoading, loadModelSettings, modelSettingsLoaded])

  const modelOptionIds = Array.from(
    new Set(
      [
        mainModel.trim(),
        subModel.trim(),
        lessonPlanModel.trim(),
        ...modelOptions.map((item) => String(item.id || '').trim()),
      ].filter(Boolean),
    ),
  )

  const updateAppearance = (patch: Partial<AppearancePreferences>) => {
    setAppearance(patch)
    scheduleAccountSave({ appearance: patch })
  }

  return (
    <div className="h-full flex flex-col md:flex-row overflow-hidden bg-background">
      {/* Sidebar */}
      <SettingsSidebar activeTab={activeTab} onSelectTab={setActiveTab} />

      {/* Content */}
      <main className="flex-1 overflow-auto p-6 md:p-10">
        <div className="max-w-2xl mx-auto space-y-8">
          {activeTab === 'account' && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div>
                <h2 className="text-lg font-medium">账户信息</h2>
                <p className="text-sm text-muted-foreground">查看和管理你的个人资料</p>
              </div>
              <Separator />
              {user ? (
                <div className="space-y-6">
                  <div className="flex items-center gap-4">
                    <div className="h-20 w-20 rounded-full bg-primary/10 text-primary flex items-center justify-center text-2xl font-bold">
                      {user.username.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <h3 className="font-semibold text-lg">{user.username}</h3>
                      {user.email && <p className="text-sm text-muted-foreground">{user.email}</p>}
                      <Badge variant="outline" className="mt-2">{roleLabel}</Badge>
                    </div>
                  </div>

                  <p className="text-sm text-muted-foreground">当前为本地模式，无需登录。</p>
                </div>
              ) : (
                <div className="text-center py-8 bg-muted/30 rounded-lg border border-dashed">
                  <p className="text-muted-foreground">当前为本地模式，无需登录。</p>
                </div>
              )}
            </div>
          )}

          {activeTab === 'api' && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div>
                <h2 className="text-lg font-medium">API 配置</h2>
                <p className="text-sm text-muted-foreground">配置模型供应商、密钥和默认模型</p>
              </div>
              <Separator />
              <div className="space-y-5">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="grid gap-2">
                    <label className="text-sm font-medium">供应商</label>
                    <Input
                      value={providerName}
                      onChange={(e) => setProviderName(e.target.value)}
                      placeholder="openrouter / deepseek / openai-compatible"
                      className="font-mono"
                    />
                  </div>
                  <div className="grid gap-2">
                    <label className="text-sm font-medium">Base URL</label>
                    <Input
                      value={providerBaseUrl}
                      onChange={(e) => setProviderBaseUrl(e.target.value)}
                      placeholder="https://api.example.com/v1"
                      className="font-mono"
                    />
                  </div>
                </div>

                <div className="grid gap-2">
                  <div className="flex items-center justify-between gap-3">
                    <label className="text-sm font-medium">API Key</label>
                    {savedApiKeyMask ? (
                      <Badge variant="outline">
                        {savedApiKeyEncrypted ? '已加密保存' : '已保存'} {savedApiKeyMask}
                      </Badge>
                    ) : null}
                  </div>
                  <div className="flex gap-2">
                    <div className="relative flex-1">
                      <Input
                        type={showProviderApiKey ? 'text' : 'password'}
                        value={providerApiKey}
                        onChange={(e) => setProviderApiKey(e.target.value)}
                        placeholder={savedApiKeyMask ? '留空则继续使用已保存密钥' : 'sk-...'}
                        className="pr-10 font-mono"
                      />
                      <button
                        type="button"
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        onClick={() => setShowProviderApiKey((v) => !v)}
                        aria-label={showProviderApiKey ? '隐藏 API Key' : '显示 API Key'}
                      >
                        {showProviderApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                    <Button variant="outline" onClick={handleFetchModels} disabled={isFetchingModels || isModelLoading}>
                      {isFetchingModels ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="h-4 w-4" />
                      )}
                      <span className="ml-2 hidden sm:inline">抓取模型</span>
                    </Button>
                  </div>
                </div>

                <datalist id="model-settings-options">
                  {modelOptionIds.map((id) => (
                    <option key={id} value={id} />
                  ))}
                </datalist>

                <div className="grid gap-4 md:grid-cols-3">
                  <div className="grid gap-2">
                    <label className="text-sm font-medium">主模型</label>
                    <Input
                      list="model-settings-options"
                      value={mainModel}
                      onChange={(e) => setMainModel(e.target.value)}
                      placeholder="openai/gpt-5-mini"
                      className="font-mono"
                    />
                  </div>
                  <div className="grid gap-2">
                    <label className="text-sm font-medium">轻量模型</label>
                    <Input
                      list="model-settings-options"
                      value={subModel}
                      onChange={(e) => setSubModel(e.target.value)}
                      placeholder="openai/gpt-4o-mini"
                      className="font-mono"
                    />
                  </div>
                  <div className="grid gap-2">
                    <label className="text-sm font-medium">教案模型</label>
                    <Input
                      list="model-settings-options"
                      value={lessonPlanModel}
                      onChange={(e) => setLessonPlanModel(e.target.value)}
                      placeholder={mainModel || 'openai/gpt-5-mini'}
                      className="font-mono"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between gap-4 rounded-lg border bg-card p-4">
                  <div>
                    <div className="text-sm font-medium">锁定当前供应商</div>
                    <div className="text-xs text-muted-foreground mt-1">模型名不会触发自动供应商切换</div>
                  </div>
                  <Switch checked={providerPinned} onCheckedChange={(checked) => setProviderPinned(Boolean(checked))} />
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <Button onClick={handleSaveModelSettings} disabled={isSavingModelSettings || isModelLoading}>
                    {isSavingModelSettings ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    <span className="ml-2">保存模型配置</span>
                  </Button>
                  <Button variant="outline" onClick={() => void loadModelSettings()} disabled={isModelLoading}>
                    {isModelLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                    <span className="ml-2">重新读取</span>
                  </Button>
                  {modelSettingsMessage ? (
                    <span
                      className={cn(
                        'text-sm',
                        /失败|failed|forbidden|http_4|http_5|Admin/i.test(modelSettingsMessage)
                          ? 'text-destructive'
                          : 'text-muted-foreground',
                      )}
                    >
                      {modelSettingsMessage}
                    </span>
                  ) : null}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'appearance' && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div>
                <h2 className="text-lg font-medium">外观</h2>
                <p className="text-sm text-muted-foreground">自定义界面主题和显示偏好</p>
              </div>
              <Separator />
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <label className="text-sm font-medium">主题</label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setTheme('system')
                      resetAppearance()
                      scheduleAccountSave({
                        theme: { mode: 'system' },
                        appearance: { sidebarStyle: 'sidebar', contentLayout: 'default', sidebarPosition: 'left' },
                      })
                    }}
                  >
                    重置
                  </Button>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  {themeOptions.map((option) => (
                    <StyleOptionCard
                      key={option.value}
                      label={option.label}
                      selected={theme === option.value}
                      onClick={() => {
                        setTheme(option.value)
                        scheduleAccountSave({ theme: { mode: option.value } })
                      }}
                    >
                      <ThemePreview mode={option.value} />
                    </StyleOptionCard>
                  ))}
                </div>
              </div>

              <div className="space-y-4">
                <label className="text-sm font-medium">侧边栏</label>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {sidebarOptions.map((option) => (
                    <StyleOptionCard
                      key={option.value}
                      label={option.label}
                      selected={sidebarStyle === option.value}
                      onClick={() => updateAppearance({ sidebarStyle: option.value })}
                    >
                      <SidebarPreview value={option.value} />
                    </StyleOptionCard>
                  ))}
                </div>
              </div>

              <div className="space-y-4">
                <label className="text-sm font-medium">布局</label>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {layoutOptions.map((option) => (
                    <StyleOptionCard
                      key={option.value}
                      label={option.label}
                      selected={contentLayout === option.value}
                      onClick={() => updateAppearance({ contentLayout: option.value })}
                    >
                      <LayoutPreview value={option.value} />
                    </StyleOptionCard>
                  ))}
                </div>
              </div>

              <div className="space-y-4">
                <label className="text-sm font-medium">方向</label>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {positionOptions.map((option) => (
                    <StyleOptionCard
                      key={option.value}
                      label={option.label}
                      selected={sidebarPosition === option.value}
                      onClick={() => updateAppearance({ sidebarPosition: option.value })}
                    >
                      <PositionPreview value={option.value} />
                    </StyleOptionCard>
                  ))}
                </div>
              </div>

              <div className="space-y-4">
                <label className="text-sm font-medium">字体大小</label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="0.85"
                    max="1.25"
                    step="0.05"
                    value={fontScale}
                    onChange={(e) => {
                      const next = Number(e.target.value)
                      setPreferences({ fontScale: next })
                      scheduleAccountSave({ ui: { fontScale: next } })
                    }}
                    className="flex-1"
                  />
                  <div className="w-14 text-right text-xs text-muted-foreground tabular-nums">
                    {Math.round(fontScale * 100)}%
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                <label className="text-sm font-medium">行距</label>
                <select
                  className="h-[var(--control-h)] rounded-md border border-input bg-background px-[var(--control-px)] text-sm w-full"
                  value={String(lineHeight)}
                  onChange={(e) => {
                    const next = Number(e.target.value)
                    setPreferences({ lineHeight: next })
                    scheduleAccountSave({ ui: { lineHeight: next } })
                  }}
                >
                  <option value="1.4">紧凑</option>
                  <option value="1.6">标准</option>
                  <option value="1.8">舒适</option>
                  <option value="2.0">宽松</option>
                </select>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">页面密度</label>
                  <select
                    className="h-[var(--control-h)] rounded-md border border-input bg-background px-[var(--control-px)] text-sm w-full"
                    value={density}
                    onChange={(e) => {
                      const next = e.target.value
                      if (next !== 'comfortable' && next !== 'compact') return
                      setPreferences({ density: next })
                      scheduleAccountSave({ ui: { density: next } })
                    }}
                  >
                    <option value="comfortable">舒适</option>
                    <option value="compact">紧凑</option>
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium">对比度模式</label>
                  <select
                    className="h-[var(--control-h)] rounded-md border border-input bg-background px-[var(--control-px)] text-sm w-full"
                    value={contrast}
                    onChange={(e) => {
                      const next = e.target.value
                      if (next !== 'normal' && next !== 'high' && next !== 'eye') return
                      setPreferences({ contrast: next })
                      scheduleAccountSave({ ui: { contrast: next } })
                    }}
                  >
                    <option value="normal">标准</option>
                    <option value="high">高对比</option>
                    <option value="eye">护眼</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center justify-between p-4 rounded-lg border bg-card">
                <div>
                  <div className="text-sm font-medium">减少动画</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    关闭大部分过渡/动效，长列表与流式页面更流畅
                  </div>
                </div>
                <Switch
                  checked={reduceMotion}
                  onCheckedChange={(checked) => {
                    setPreferences({ reduceMotion: Boolean(checked) })
                    scheduleAccountSave({ ui: { reduceMotion: Boolean(checked) } })
                  }}
                />
              </div>

              {isAuthenticated && (
                <div className="text-xs text-muted-foreground">
                  {isSyncing ? '正在保存本地配置…' : '本地配置已保存'}
                  {syncError ? <span className="text-destructive">（同步失败：{syncError}）</span> : null}
                </div>
              )}
            </div>
          )}

          {activeTab === 'data' && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div>
                <h2 className="text-lg font-medium">数据管理</h2>
                <p className="text-sm text-muted-foreground">管理本地存储的数据</p>
              </div>
              <Separator />
              <div className="space-y-4">
                <div className="flex items-center justify-between p-4 rounded-lg border bg-card">
                  <div>
                    <h4 className="font-medium text-sm">清除本地缓存</h4>
                    <p className="text-xs text-muted-foreground mt-1">
                      清除浏览器中存储的所有临时数据和状态
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      if (confirm('确定要清除所有本地数据吗？此操作不可恢复。')) {
                        localStorage.clear()
                        window.location.reload()
                      }
                    }}
                  >
                    清除
                  </Button>
                </div>

                <div className="p-4 rounded-lg border bg-card space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h4 className="font-medium text-sm">本地配置</h4>
                      <p className="text-xs text-muted-foreground mt-1">
                        主题与显示偏好将保存在本地默认用户下。
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={async () => {
                        const settings = await exportFromServer()
                        const blob = new Blob([JSON.stringify(settings, null, 2)], { type: 'application/json' })
                        const url = URL.createObjectURL(blob)
                        const a = document.createElement('a')
                        a.href = url
                        a.download = `user-settings-${new Date().toISOString().slice(0, 10)}.json`
                        a.click()
                        URL.revokeObjectURL(url)
                      }}
                      disabled={!isAuthenticated}
                    >
                      导出配置
                    </Button>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" size="sm" asChild disabled={!isAuthenticated}>
                      <label className="cursor-pointer">
                        导入配置
                        <input
                          type="file"
                          accept="application/json"
                          className="hidden"
                          onChange={async (e) => {
                            const file = e.target.files?.[0]
                            if (!file) return
                            try {
                              const text = await file.text()
                              const parsed = JSON.parse(text) as unknown
                              if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
                                alert('配置文件格式不正确')
                                return
                              }
                              await importToServer(parsed as Record<string, unknown>)
                              // Apply imported settings immediately
                              const parsedObj = parsed as Record<string, unknown>
                              const themeObj = isRecord(parsedObj.theme) ? parsedObj.theme : {}
                              const themeMode = String(themeObj.mode || '').trim()
                              if (themeMode === 'light' || themeMode === 'dark' || themeMode === 'system') {
                                setTheme(themeMode)
                              }
                              const ui = parsedObj.ui
                              if (isRecord(ui)) {
                                const densityValue = String(ui.density || '').trim()
                                const contrastValue = String(ui.contrast || '').trim()
                                const uiPatch: {
                                  fontScale?: number
                                  lineHeight?: number
                                  density?: UiDensity
                                  contrast?: UiContrast
                                  reduceMotion?: boolean
                                } = {
                                  ...(ui.fontScale !== undefined ? { fontScale: Number(ui.fontScale) } : {}),
                                  ...(ui.lineHeight !== undefined ? { lineHeight: Number(ui.lineHeight) } : {}),
                                  ...(densityValue === 'comfortable' || densityValue === 'compact'
                                    ? { density: densityValue }
                                    : {}),
                                  ...(contrastValue === 'normal' || contrastValue === 'high' || contrastValue === 'eye'
                                    ? { contrast: contrastValue }
                                    : {}),
                                  ...(ui.reduceMotion !== undefined ? { reduceMotion: Boolean(ui.reduceMotion) } : {}),
                                }
                                setPreferences(uiPatch)
                              }
                              const appearance = parsedObj.appearance
                              if (isRecord(appearance)) {
                                const sidebarStyleValue = String(appearance.sidebarStyle || '').trim()
                                const contentLayoutValue = String(appearance.contentLayout || '').trim()
                                const sidebarPositionValue = String(appearance.sidebarPosition || '').trim()
                                const appearancePatch: Partial<AppearancePreferences> = {
                                  ...(sidebarStyleValue === 'inset' ||
                                  sidebarStyleValue === 'floating' ||
                                  sidebarStyleValue === 'sidebar'
                                    ? { sidebarStyle: sidebarStyleValue }
                                    : {}),
                                  ...(contentLayoutValue === 'default' ||
                                  contentLayoutValue === 'compact' ||
                                  contentLayoutValue === 'full'
                                    ? { contentLayout: contentLayoutValue }
                                    : {}),
                                  ...(sidebarPositionValue === 'left' || sidebarPositionValue === 'right'
                                    ? { sidebarPosition: sidebarPositionValue }
                                    : {}),
                                }
                                setAppearance(appearancePatch)
                              }
                              alert('已导入并保存到本地配置')
                            } catch {
                              alert('读取或解析配置失败')
                            } finally {
                              e.target.value = ''
                            }
                          }}
                        />
                      </label>
                    </Button>

                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!isAuthenticated}
                      onClick={async () => {
                        if (!confirm('恢复默认配置？这会覆盖当前本地配置。')) return
                        await resetToDefaults()
                        setTheme('system')
                        resetPreferences()
                        resetAppearance()
                        alert('已恢复默认配置')
                      }}
                    >
                      恢复默认
                    </Button>
                  </div>
                </div>

                <div className="flex items-center justify-between p-4 rounded-lg border bg-card">
                  <div>
                    <h4 className="font-medium text-sm">导出所有数据</h4>
                    <p className="text-xs text-muted-foreground mt-1">
                      将所有试卷和自学资料导出为 JSON 文件
                    </p>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => {
                    const exportData: Record<string, unknown> = {}
                    for (let i = 0; i < localStorage.length; i++) {
                      const key = localStorage.key(i)
                      if (key) {
                        try {
                          exportData[key] = JSON.parse(localStorage.getItem(key) || '')
                        } catch {
                          exportData[key] = localStorage.getItem(key)
                        }
                      }
                    }
                    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
                    const url = URL.createObjectURL(blob)
                    const a = document.createElement('a')
                    a.href = url
                    a.download = `study-ai-export-${new Date().toISOString().slice(0, 10)}.json`
                    a.click()
                    URL.revokeObjectURL(url)
                  }}>导出</Button>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'about' && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div>
                <h2 className="text-lg font-medium">关于</h2>
                <p className="text-sm text-muted-foreground">应用版本信息</p>
              </div>
              <Separator />
              <div className="space-y-4">
                <div className="flex justify-between py-2 border-b border-border/50">
                  <span className="text-sm text-muted-foreground">版本</span>
                  <span className="text-sm font-medium">0.1.0</span>
                </div>
                <div className="flex justify-between py-2 border-b border-border/50">
                  <span className="text-sm text-muted-foreground">构建时间</span>
                  <span className="text-sm font-medium">{new Date().toLocaleDateString('zh-CN')}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-border/50">
                  <span className="text-sm text-muted-foreground">开发者</span>
                  <span className="text-sm font-medium">AI Assistant</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
