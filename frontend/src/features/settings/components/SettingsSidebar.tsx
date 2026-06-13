import { Activity, Info, Key, Palette, Database, User } from 'lucide-react'
import { cn } from '@/lib/utils'

export type SettingsTabId = 'account' | 'api' | 'appearance' | 'data' | 'debug' | 'about'

const tabs: Array<{ id: SettingsTabId; label: string; icon: any }> = [
  { id: 'account', label: '账户', icon: User },
  { id: 'api', label: '模型连接', icon: Key },
  { id: 'appearance', label: '外观', icon: Palette },
  { id: 'data', label: '数据管理', icon: Database },
  { id: 'debug', label: '调试', icon: Activity },
  { id: 'about', label: '关于', icon: Info },
]

export function SettingsSidebar(opts: { activeTab: SettingsTabId; onSelectTab: (tab: SettingsTabId) => void }) {
  const { activeTab, onSelectTab } = opts

  return (
    <aside className="aurora-settings-sidebar w-full md:w-64 p-4 md:p-6 overflow-x-auto md:overflow-y-auto flex-shrink-0">
      <div className="mb-6 hidden md:block">
        <h1 className="text-2xl font-bold tracking-tight">设置</h1>
        <p className="text-sm text-muted-foreground mt-1">管理你的账户和应用偏好</p>
      </div>

      <nav className="flex md:flex-col gap-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onSelectTab(tab.id)}
            className={cn(
              'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors whitespace-nowrap',
              activeTab === tab.id
                ? 'aurora-settings-tab is-active'
                : 'aurora-settings-tab text-muted-foreground hover:text-foreground'
            )}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
          </button>
        ))}
      </nav>
    </aside>
  )
}

