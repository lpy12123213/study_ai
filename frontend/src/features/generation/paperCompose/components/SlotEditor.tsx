
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { BlueprintSlot } from '@/types'

export interface SlotEditorProps {
  slot: BlueprintSlot
  onUpdate: (slot: BlueprintSlot) => void
  onRemove: () => void
}

export function SlotEditor({ slot, onUpdate, onRemove }: SlotEditorProps) {
  return (
    <div className="grid grid-cols-12 gap-3 items-center py-3 border-b border-border/50 last:border-0 text-sm hover:bg-muted/30 transition-colors px-2 rounded-md">
      <div className="col-span-3 font-medium">{slot.questionType}</div>
      <div className="col-span-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-8">数量</span>
          <Input
            type="number"
            min={1}
            max={50}
            value={slot.count}
            onChange={(e) => onUpdate({ ...slot, count: parseInt(e.target.value) || 1 })}
            className="h-8"
          />
        </div>
      </div>
      <div className="col-span-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-8">分值</span>
          <Input
            type="number"
            min={1}
            max={100}
            value={slot.score || 0}
            onChange={(e) => onUpdate({ ...slot, score: parseInt(e.target.value) || 0 })}
            className="h-8"
          />
        </div>
      </div>
      <div className="col-span-2">
        <Select
          value={slot.difficulty || 'medium'}
          onValueChange={(value) => onUpdate({ ...slot, difficulty: value })}
        >
          <SelectTrigger className="h-8 w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="easy">简单</SelectItem>
            <SelectItem value="medium">中等</SelectItem>
            <SelectItem value="hard">困难</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="col-span-1 text-right">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
