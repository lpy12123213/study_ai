import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { isRecord } from '@/lib/record'
import {
  isDesignStylePreset,
  type AppearancePreferences,
  type DesignStylePreset,
} from '@/stores/useAppearanceStore'
import type { UiContrast, UiDensity } from '@/stores/useUiPreferencesStore'

export type DataPanelProps = {
  isAuthenticated: boolean
  exportFromServer: () => Promise<unknown>
  importToServer: (settings: Record<string, unknown>) => Promise<void>
  resetToDefaults: () => Promise<void>
  setTheme: (mode: 'system' | 'light' | 'dark') => void
  setPreferences: (patch: {
    fontScale?: number
    lineHeight?: number
    density?: UiDensity
    contrast?: UiContrast
    reduceMotion?: boolean
  }) => void
  resetPreferences: () => void
  setAppearance: (patch: Partial<AppearancePreferences>) => void
  resetAppearance: () => void
}

function applyImportedSettings(parsed: Record<string, unknown>, props: DataPanelProps) {
  const themeObj = isRecord(parsed.theme) ? parsed.theme : {}
  const themeMode = String(themeObj.mode || '').trim()
  if (themeMode === 'light' || themeMode === 'dark' || themeMode === 'system') {
    props.setTheme(themeMode)
  }

  const ui = parsed.ui
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
      ...(densityValue === 'comfortable' || densityValue === 'compact' ? { density: densityValue } : {}),
      ...(contrastValue === 'normal' || contrastValue === 'high' || contrastValue === 'eye'
        ? { contrast: contrastValue }
        : {}),
      ...(ui.reduceMotion !== undefined ? { reduceMotion: Boolean(ui.reduceMotion) } : {}),
    }
    props.setPreferences(uiPatch)
  }

  const appearance = parsed.appearance
  if (isRecord(appearance)) {
    const sidebarStyleValue = String(appearance.sidebarStyle || '').trim()
    const contentLayoutValue = String(appearance.contentLayout || '').trim()
    const sidebarPositionValue = String(appearance.sidebarPosition || '').trim()
    const designStyleValue = String(appearance.designStyle || '').trim()
    const appearancePatch: Partial<AppearancePreferences> = {
      ...(isDesignStylePreset(designStyleValue)
        ? { designStyle: designStyleValue as DesignStylePreset }
        : {}),
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
    props.setAppearance(appearancePatch)
  }
}

export function DataPanel(props: DataPanelProps) {
  const {
    isAuthenticated,
    exportFromServer,
    importToServer,
    resetToDefaults,
    setTheme,
    resetPreferences,
    resetAppearance,
  } = props

  const handleExport = async () => {
    const settings = await exportFromServer()
    const blob = new Blob([JSON.stringify(settings, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `user-settings-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const text = await file.text()
      const parsed: unknown = JSON.parse(text)
      if (!isRecord(parsed)) {
        alert('配置文件格式不正确')
        return
      }
      await importToServer(parsed)
      applyImportedSettings(parsed, props)
      alert('已导入并保存到本地配置')
    } catch {
      alert('读取或解析配置失败')
    } finally {
      e.target.value = ''
    }
  }

  const handleResetToDefaults = async () => {
    if (!confirm('恢复默认配置？这会覆盖当前本地配置。')) return
    await resetToDefaults()
    setTheme('system')
    resetPreferences()
    resetAppearance()
    alert('已恢复默认配置')
  }

  const handleExportAll = () => {
    const exportData: Record<string, unknown> = {}
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key) continue
      try {
        exportData[key] = JSON.parse(localStorage.getItem(key) || '')
      } catch {
        exportData[key] = localStorage.getItem(key)
      }
    }
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `study-ai-export-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
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
            <p className="text-xs text-muted-foreground mt-1">清除浏览器中存储的所有临时数据和状态</p>
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
            <Button variant="outline" size="sm" onClick={() => void handleExport()} disabled={!isAuthenticated}>
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
                  onChange={(e) => void handleImport(e)}
                />
              </label>
            </Button>

            <Button
              variant="outline"
              size="sm"
              disabled={!isAuthenticated}
              onClick={() => void handleResetToDefaults()}
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
          <Button variant="outline" size="sm" onClick={handleExportAll}>
            导出
          </Button>
        </div>
      </div>
    </div>
  )
}
