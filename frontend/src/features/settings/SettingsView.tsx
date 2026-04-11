import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  LogOut,
  Save,
  Loader2,
  Monitor,
  Moon,
  Sun,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { useAuthStore } from '@/stores/useAuthStore'
import { useThemeStore } from '@/stores/useThemeStore'
import { useUiPreferencesStore } from '@/stores/useUiPreferencesStore'
import { useUserSettingsStore } from '@/stores/useUserSettingsStore'
import { cn } from '@/lib/utils'
import { SettingsSidebar, type SettingsTabId } from '@/features/settings/components/SettingsSidebar'

const roleLabels: Record<string, string> = {
  admin: '管理员',
  user: '普通用户',
}

export default function SettingsView() {
  const [activeTab, setActiveTab] = useState<SettingsTabId>('account')
  const { user, logout, isAuthenticated } = useAuthStore()
  const { theme, setTheme } = useThemeStore()
  const { fontScale, lineHeight, density, contrast, reduceMotion, setPreferences, resetPreferences } = useUiPreferencesStore()
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

  const [apiKey, setApiKey] = useState(() => localStorage.getItem('settings_api_key') || '')
  const [isSaving, setIsSaving] = useState(false)

  const handleSaveApiKey = async () => {
    setIsSaving(true)
    try {
      const cleaned = apiKey.trim()
      if (cleaned) {
        localStorage.setItem('settings_api_key', cleaned)
        localStorage.setItem('settings_api_key_enabled', '1')
        localStorage.removeItem('settings_api_key_disabled_reason')
      } else {
        localStorage.removeItem('settings_api_key')
        localStorage.removeItem('settings_api_key_enabled')
        localStorage.removeItem('settings_api_key_disabled_reason')
      }
    } finally {
      setIsSaving(false)
    }
  }

  const handleLogout = () => {
    if (confirm('确定要退出登录吗？')) {
      logout()
      window.location.href = '/login'
    }
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

                  <div className="pt-4">
                    <Button variant="destructive" onClick={handleLogout}>
                      <LogOut className="h-4 w-4 mr-2" />
                      退出登录
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="text-center py-8 bg-muted/30 rounded-lg border border-dashed">
                  <p className="text-muted-foreground mb-4">你当前处于访客模式</p>
                  <Button asChild>
                    <Link to="/login">登录 / 注册</Link>
                  </Button>
                </div>
              )}
            </div>
          )}

          {activeTab === 'api' && (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div>
                <h2 className="text-lg font-medium">API 配置</h2>
                <p className="text-sm text-muted-foreground">配置 AI 服务的连接密钥</p>
              </div>
              <Separator />
              <div className="space-y-4">
                <div className="grid gap-2">
                  <label className="text-sm font-medium">OpenAI API Key</label>
                  <div className="flex gap-2">
                    <Input
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="sk-..."
                      className="flex-1 font-mono"
                    />
                    <Button onClick={handleSaveApiKey} disabled={isSaving}>
                      {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    </Button>
                  </div>
                  <p className="text-[13px] text-muted-foreground">
                    密钥将保存在本地浏览器中，并在请求时通过请求头发送到你的后端用于调用模型；后端不会持久化或记录该密钥。
                  </p>
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
                <label className="text-sm font-medium">主题模式</label>
                <div className="grid grid-cols-3 gap-4">
                  {[
                    { value: 'light', label: '浅色', icon: Sun },
                    { value: 'dark', label: '深色', icon: Moon },
                    { value: 'system', label: '跟随系统', icon: Monitor },
                  ].map((option) => (
                    <div
                      key={option.value}
                      className={cn(
                        "cursor-pointer rounded-lg border-2 border-muted bg-popover p-4 hover:bg-accent hover:text-accent-foreground",
                        theme === option.value && "border-primary"
                      )}
                      onClick={() => {
                        setTheme(option.value as any)
                        scheduleAccountSave({ theme: { mode: option.value } })
                      }}
                    >
                      <div className="mb-2 rounded-md bg-background p-2 w-fit border shadow-sm">
                        <option.icon className="h-5 w-5" />
                      </div>
                      <div className="font-medium text-sm">{option.label}</div>
                    </div>
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
                  {isSyncing ? '正在同步到账号…' : '已同步到账号'}
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
                      <h4 className="font-medium text-sm">账号配置（跨设备同步）</h4>
                      <p className="text-xs text-muted-foreground mt-1">
                        主题与显示偏好将保存在账号中；清空浏览器数据后重新登录可恢复。
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
                              const themeMode = String((parsed as any)?.theme?.mode || '').trim()
                              if (themeMode === 'light' || themeMode === 'dark' || themeMode === 'system') {
                                setTheme(themeMode as any)
                              }
                              const ui = (parsed as any)?.ui
                              if (ui && typeof ui === 'object' && !Array.isArray(ui)) {
                                setPreferences({
                                  ...(ui.fontScale !== undefined ? { fontScale: Number(ui.fontScale) } : {}),
                                  ...(ui.lineHeight !== undefined ? { lineHeight: Number(ui.lineHeight) } : {}),
                                  ...(ui.density ? { density: String(ui.density) as any } : {}),
                                  ...(ui.contrast ? { contrast: String(ui.contrast) as any } : {}),
                                  ...(ui.reduceMotion !== undefined ? { reduceMotion: Boolean(ui.reduceMotion) } : {}),
                                })
                              }
                              alert('已导入并同步到账号')
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
                        if (!confirm('恢复默认配置？这会覆盖你账号中已同步的设置。')) return
                        await resetToDefaults()
                        setTheme('system')
                        resetPreferences()
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
