import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import {
  DESIGN_STYLE_PRESETS,
  type AppearancePreferences,
  type ContentLayout,
  type SidebarPosition,
  type SidebarStyle,
} from '@/stores/useAppearanceStore'
import {
  DesignStylePreview,
  LayoutPreview,
  PositionPreview,
  SidebarPreview,
  StyleOptionCard,
  ThemePreview,
} from '@/features/settings/components/appearancePreviews'

type ThemeMode = 'system' | 'light' | 'dark'

const themeOptions: Array<{ value: ThemeMode; label: string }> = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

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

export type AppearancePanelProps = {
  theme: ThemeMode
  setTheme: (next: ThemeMode) => void
  designStyle: AppearancePreferences['designStyle']
  sidebarStyle: SidebarStyle
  contentLayout: ContentLayout
  sidebarPosition: SidebarPosition
  fontScale: number
  lineHeight: number
  density: 'comfortable' | 'compact'
  contrast: 'normal' | 'high' | 'eye'
  reduceMotion: boolean
  isAuthenticated: boolean
  isSyncing: boolean
  syncError: string | null
  resetAppearance: () => void
  resetPreferences: () => void
  updateAppearance: (patch: Partial<AppearancePreferences>) => void
  setPreferences: (patch: {
    fontScale?: number
    lineHeight?: number
    density?: 'comfortable' | 'compact'
    contrast?: 'normal' | 'high' | 'eye'
    reduceMotion?: boolean
  }) => void
  scheduleAccountSave: (patch: Record<string, unknown>) => void
}

export function AppearancePanel(props: AppearancePanelProps) {
  const {
    theme,
    setTheme,
    designStyle,
    sidebarStyle,
    contentLayout,
    sidebarPosition,
    fontScale,
    lineHeight,
    density,
    contrast,
    reduceMotion,
    isAuthenticated,
    isSyncing,
    syncError,
    resetAppearance,
    updateAppearance,
    setPreferences,
    scheduleAccountSave,
  } = props

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div>
        <h2 className="text-lg font-medium">外观</h2>
        <p className="text-sm text-muted-foreground">自定义界面主题和显示偏好</p>
      </div>
      <Separator />
      <div className="space-y-4">
        <div>
          <label className="text-sm font-medium">样式库</label>
          <p className="mt-1 text-xs text-muted-foreground">
            来源于 VoltAgent/awesome-design-md 的品牌设计语言，切换后会立即应用全局配色与界面质感。
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {DESIGN_STYLE_PRESETS.map((option) => (
            <StyleOptionCard
              key={option.value}
              label={option.label}
              description={option.source}
              selected={designStyle === option.value}
              onClick={() => updateAppearance({ designStyle: option.value })}
            >
              <DesignStylePreview preset={option} />
            </StyleOptionCard>
          ))}
        </div>
      </div>

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
                appearance: {
                  designStyle: 'cursor',
                  sidebarStyle: 'sidebar',
                  contentLayout: 'default',
                  sidebarPosition: 'left',
                },
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
  )
}
