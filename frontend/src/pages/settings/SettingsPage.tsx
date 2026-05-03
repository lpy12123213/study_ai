import { useAuthStore } from '@/stores/useAuthStore'
import { useThemeStore } from '@/stores/useThemeStore'

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user)
  const { theme, toggleTheme } = useThemeStore()

  return (
    <div className="space-y-8 max-w-lg">
      <h1 className="text-2xl font-semibold">设置</h1>
      <div className="space-y-2">
        <h2 className="font-medium">账户</h2>
        <p className="text-sm text-muted-foreground">
          用户名：{user?.username} 角色：{user?.role}
        </p>
      </div>
      <div className="space-y-3">
        <h2 className="font-medium">外观</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm">主题</span>
          <button onClick={toggleTheme} className="px-3 py-1.5 border rounded-md text-sm hover:bg-accent transition-colors">
            {theme === 'dark' ? '切换到浅色' : '切换到深色'}
          </button>
        </div>
      </div>
    </div>
  )
}
