import { Info, Key, Palette, Database, User } from 'lucide-react'
import { cn } from '@/lib/utils'

export type SettingsTabId = 'account' | 'api' | 'appearance' | 'data' | 'about'

const tabs: Array<{ id: SettingsTabId; label: string; icon: any }> = [
  { id: 'account', label: '账户', icon: User },
  { id: 'api', label: 'API 配置', icon: Key },
  { id: 'appearance', label: '外观', icon: Palette },
  { id: 'data', label: '数据管理', icon: Database },
  { id: 'about', label: '关于', icon: Info },
]

export function SettingsSidebar(opts: { activeTab: SettingsTabId; onSelectTab: (tab: SettingsTabId) => void }) {
  const { activeTab, onSelectTab } = opts

  return (
    <aside className="w-full md:w-64 border-b md:border-b-0 md:border-r border-border bg-muted/30 p-4 md:p-6 overflow-x-auto md:overflow-y-auto flex-shrink-0">
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
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
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

