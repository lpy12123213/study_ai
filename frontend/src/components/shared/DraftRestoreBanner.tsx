import { RotateCcw, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type DraftRestoreBannerProps = {
  className?: string
  description?: string
  onDiscard: () => void
  onRestore: () => void
  visible: boolean
}

export function DraftRestoreBanner({
  className,
  description = '检测到未提交草稿',
  onDiscard,
  onRestore,
  visible,
}: DraftRestoreBannerProps) {
  if (!visible) return null

  return (
    <div
      className={cn(
        'aurora-draft-restore-banner flex flex-col gap-3 rounded-lg px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between',
        className
      )}
    >
      <div className="text-muted-foreground">{description}</div>
      <div className="flex items-center gap-2">
        <Button type="button" className="aurora-shared-primary-action" size="sm" onClick={onRestore}>
          <RotateCcw className="mr-2 h-4 w-4" />
          恢复
        </Button>
        <Button type="button" className="aurora-shared-secondary-action" size="sm" variant="ghost" onClick={onDiscard}>
          <X className="mr-2 h-4 w-4" />
          丢弃
        </Button>
      </div>
    </div>
  )
}
