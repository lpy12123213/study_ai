import { FileText, Loader2, Pause, Play, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export interface BlueprintActionBarProps {
  blueprintName: string
  onBlueprintNameChange: (value: string) => void
  subject: string
  slotsCount: number
  isSaving: boolean
  onSaveBlueprint: () => void
  isComposing: boolean
  isPaused: boolean
  onPause: () => void
  onResume: () => void
  onCompose: () => void
}

export function BlueprintActionBar({
  blueprintName,
  onBlueprintNameChange,
  subject,
  slotsCount,
  isSaving,
  onSaveBlueprint,
  isComposing,
  isPaused,
  onPause,
  onResume,
  onCompose,
}: BlueprintActionBarProps) {
  return (
    <div className="flex items-center gap-3 pt-4 border-t border-border">
      <div className="flex-1 flex items-center gap-2">
        <Input
          placeholder="蓝图名称"
          value={blueprintName}
          onChange={(e) => onBlueprintNameChange(e.target.value)}
          className="max-w-[240px]"
        />
        <Button
          variant="ghost"
          onClick={onSaveBlueprint}
          disabled={!blueprintName || !subject || slotsCount === 0 || isSaving}
        >
          <Save className="h-4 w-4 mr-2" />
          保存
        </Button>
      </div>

      {isComposing ? (
        <Button variant="destructive" onClick={onPause} className="w-32">
          <Pause className="h-4 w-4 mr-2" />
          暂停
        </Button>
      ) : isPaused ? (
        <Button onClick={onResume} className="w-32 bg-primary text-primary-foreground hover:bg-primary/90">
          <Play className="h-4 w-4 mr-2" />
          继续
        </Button>
      ) : (
        <Button
          onClick={onCompose}
          disabled={!subject || slotsCount === 0}
          className="w-32 bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
        >
          {isComposing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <FileText className="h-4 w-4 mr-2" />}
          开始组卷
        </Button>
      )}
    </div>
  )
}
