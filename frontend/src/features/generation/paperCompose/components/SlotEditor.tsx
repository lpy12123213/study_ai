import { useEffect, useState } from 'react'
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
  const [countText, setCountText] = useState(String(slot.count || 1))
  const [scoreText, setScoreText] = useState(String(slot.score ?? 0))

  useEffect(() => {
    setCountText(String(slot.count || 1))
  }, [slot.count])

  useEffect(() => {
    setScoreText(String(slot.score ?? 0))
  }, [slot.score])

  const commitCount = () => {
    const parsed = Number.parseInt(countText, 10)
    const next = Number.isFinite(parsed) ? Math.max(1, Math.min(50, parsed)) : slot.count || 1
    setCountText(String(next))
    if (next !== slot.count) onUpdate({ ...slot, count: next })
  }

  const commitScore = () => {
    const parsed = Number.parseInt(scoreText, 10)
    const next = Number.isFinite(parsed) ? Math.max(0, Math.min(100, parsed)) : slot.score || 0
    setScoreText(String(next))
    if (next !== (slot.score || 0)) onUpdate({ ...slot, score: next })
  }

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
            value={countText}
            onChange={(e) => setCountText(e.target.value)}
            onBlur={commitCount}
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
            value={scoreText}
            onChange={(e) => setScoreText(e.target.value)}
            onBlur={commitScore}
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
