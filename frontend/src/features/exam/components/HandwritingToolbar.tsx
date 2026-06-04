import { RotateCcw, RotateCw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface HandwritingToolbarProps {
  color: string
  width: number
  onColorChange: (color: string) => void
  onWidthChange: (width: number) => void
  onUndo: () => void
  onRedo: () => void
  onClear: () => void
}

const COLORS = ['#111827', '#2563eb', '#dc2626']

export function HandwritingToolbar({
  color,
  width,
  onColorChange,
  onWidthChange,
  onUndo,
  onRedo,
  onClear,
}: HandwritingToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b p-2">
      <div className="flex items-center gap-1">
        {COLORS.map((item) => (
          <button
            key={item}
            type="button"
            className={cn('h-7 w-7 rounded-full border', color === item && 'ring-2 ring-ring ring-offset-2')}
            style={{ backgroundColor: item }}
            aria-label={`颜色 ${item}`}
            onClick={() => onColorChange(item)}
          />
        ))}
      </div>
      <input
        type="range"
        min={2}
        max={6}
        value={width}
        onChange={(event) => onWidthChange(Number(event.target.value))}
        className="w-28"
        aria-label="笔画粗细"
      />
      <div className="ml-auto flex items-center gap-1">
        <Button type="button" variant="ghost" size="icon" onClick={onUndo} title="撤销">
          <RotateCcw className="h-4 w-4" />
        </Button>
        <Button type="button" variant="ghost" size="icon" onClick={onRedo} title="重做">
          <RotateCw className="h-4 w-4" />
        </Button>
        <Button type="button" variant="ghost" size="icon" onClick={onClear} title="清空">
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
