import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  User,
  Key,
  Palette,
  Database,
  LogOut,
  Save,
  Loader2,
  Monitor,
  Moon,
  Sun,
  Info
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { useAuthStore } from '@/stores/useAuthStore'
import { useThemeStore } from '@/stores/useThemeStore'
import { cn } from '@/lib/utils'

const tabs = [
  { id: 'account', label: '账户', icon: User },
  { id: 'api', label: 'API 配置', icon: Key },
  { id: 'appearance', label: '外观', icon: Palette },
  { id: 'data', label: '数据管理', icon: Database },
  { id: 'about', label: '关于', icon: Info },
]

const roleLabels: Record<string, string> = {
  admin: '管理员',
  user: '普通用户',
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState('account')
  const { user, logout } = useAuthStore()
  const { theme, setTheme } = useThemeStore()
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
      localStorage.setItem('settings_api_key', apiKey)
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
      <aside className="w-full md:w-64 border-b md:border-b-0 md:border-r border-border bg-muted/30 p-4 md:p-6 overflow-x-auto md:overflow-y-auto flex-shrink-0">
        <div className="mb-6 hidden md:block">
          <h1 className="text-2xl font-bold tracking-tight">设置</h1>
          <p className="text-sm text-muted-foreground mt-1">管理你的账户和应用偏好</p>
        </div>

        <nav className="flex md:flex-col gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap",
                activeTab === tab.id
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </button>
          ))}
        </nav>
      </aside>

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
                      onClick={() => setTheme(option.value as any)}
                    >
                      <div className="mb-2 rounded-md bg-background p-2 w-fit border shadow-sm">
                        <option.icon className="h-5 w-5" />
                      </div>
                      <div className="font-medium text-sm">{option.label}</div>
                    </div>
                  ))}
                </div>
              </div>
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
