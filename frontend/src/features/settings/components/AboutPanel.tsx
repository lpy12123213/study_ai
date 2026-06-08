import { Separator } from '@/components/ui/separator'

const buildTime = String(import.meta.env.VITE_BUILD_TIME || '').trim()

export function AboutPanel() {
  return (
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
          <span className="text-sm font-medium">
            {buildTime ? new Date(buildTime).toLocaleDateString('zh-CN') : '开发环境'}
          </span>
        </div>
        <div className="flex justify-between py-2 border-b border-border/50">
          <span className="text-sm text-muted-foreground">开发者</span>
          <span className="text-sm font-medium">AI Assistant</span>
        </div>
      </div>
    </div>
  )
}
