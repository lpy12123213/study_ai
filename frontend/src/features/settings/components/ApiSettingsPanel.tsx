import { useEffect, useMemo } from 'react'
import { Eye, EyeOff, Loader2, RefreshCw, Save } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import type { ApiSettingsHook } from '@/features/settings/hooks/useApiSettings'

type Props = {
  api: ApiSettingsHook
  isActive: boolean
}

export function ApiSettingsPanel({ api, isActive }: Props) {
  useEffect(() => {
    if (!isActive) return
    if (api.modelSettingsLoaded || api.isModelLoading) return
    void api.loadModelSettings()
  }, [api, isActive])

  const modelOptionIds = useMemo(
    () =>
      Array.from(
        new Set(
          [
            api.mainModel.trim(),
            api.subModel.trim(),
            api.lessonPlanModel.trim(),
            ...api.modelOptions.map((item) => String(item.id || '').trim()),
          ].filter(Boolean),
        ),
      ),
    [api.mainModel, api.subModel, api.lessonPlanModel, api.modelOptions],
  )

  return (
    <div className="aurora-settings-panel space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div>
        <h2 className="text-lg font-medium">模型连接</h2>
        <p className="text-sm text-muted-foreground">配置智能服务通道、访问密钥和默认模型</p>
      </div>
      <Separator />
      <div className="space-y-5">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="grid gap-2">
            <label className="text-sm font-medium">服务通道</label>
            <Input
              value={api.providerName}
              onChange={(e) => api.setProviderName(e.target.value)}
              placeholder="默认通道 / 自定义通道"
              className="font-mono"
            />
          </div>
          <div className="grid gap-2">
            <label className="text-sm font-medium">服务地址</label>
            <Input
              value={api.providerBaseUrl}
              onChange={(e) => api.setProviderBaseUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
              className="font-mono"
            />
          </div>
        </div>

        <div className="grid gap-2">
          <div className="flex items-center justify-between gap-3">
            <label className="text-sm font-medium">访问密钥</label>
            {api.savedApiKeyMask ? (
              <Badge variant="outline">
                {api.savedApiKeyEncrypted ? '已加密保存' : '已保存'} {api.savedApiKeyMask}
              </Badge>
            ) : null}
          </div>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Input
                type={api.showProviderApiKey ? 'text' : 'password'}
                value={api.providerApiKey}
                onChange={(e) => api.setProviderApiKey(e.target.value)}
                placeholder={api.savedApiKeyMask ? '留空则继续使用已保存密钥' : '输入访问密钥'}
                className="pr-10 font-mono"
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={api.toggleShowApiKey}
                aria-label={api.showProviderApiKey ? '隐藏访问密钥' : '显示访问密钥'}
              >
                {api.showProviderApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <Button
              variant="outline"
              onClick={() => void api.fetchProviderModels()}
              disabled={api.isFetchingModels || api.isModelLoading}
            >
              {api.isFetchingModels ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              <span className="ml-2 hidden sm:inline">读取模型</span>
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
              value={api.mainModel}
              onChange={(e) => api.setMainModel(e.target.value)}
              placeholder="选择或填写主模型"
              className="font-mono"
            />
          </div>
          <div className="grid gap-2">
            <label className="text-sm font-medium">轻量模型</label>
            <Input
              list="model-settings-options"
              value={api.subModel}
              onChange={(e) => api.setSubModel(e.target.value)}
              placeholder="选择或填写轻量模型"
              className="font-mono"
            />
          </div>
          <div className="grid gap-2">
            <label className="text-sm font-medium">教案模型</label>
            <Input
              list="model-settings-options"
              value={api.lessonPlanModel}
              onChange={(e) => api.setLessonPlanModel(e.target.value)}
              placeholder={api.mainModel || '选择或填写教案模型'}
              className="font-mono"
            />
          </div>
        </div>

        <div className="aurora-settings-card flex items-center justify-between gap-4 rounded-lg p-4">
          <div>
            <div className="text-sm font-medium">锁定当前通道</div>
            <div className="text-xs text-muted-foreground mt-1">模型选择不会自动切换服务通道</div>
          </div>
          <Switch checked={api.providerPinned} onCheckedChange={(checked) => api.setProviderPinned(Boolean(checked))} />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => void api.saveModelSettings()}
            disabled={api.isSavingModelSettings || api.isModelLoading}
          >
            {api.isSavingModelSettings ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            <span className="ml-2">保存模型配置</span>
          </Button>
          <Button variant="outline" onClick={() => void api.loadModelSettings()} disabled={api.isModelLoading}>
            {api.isModelLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            <span className="ml-2">重新读取</span>
          </Button>
          {api.modelSettingsMessage ? (
            <span
              className={cn(
                'text-sm',
                /失败|failed|forbidden|http_4|http_5|Admin/i.test(api.modelSettingsMessage)
                  ? 'text-destructive'
                  : 'text-muted-foreground',
              )}
            >
              {api.modelSettingsMessage}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  )
}
