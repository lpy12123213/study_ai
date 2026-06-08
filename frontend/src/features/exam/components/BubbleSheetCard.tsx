import { Checkbox } from '@/components/ui/checkbox'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { cn } from '@/lib/utils'

const DEFAULT_OPTIONS = ['A', 'B', 'C', 'D']

interface BubbleSheetCardProps {
  mode: 'single' | 'multi'
  options?: string[]
  value: string[]
  onChange: (value: string[]) => void
}

export function BubbleSheetCard({ mode, options = DEFAULT_OPTIONS, value, onChange }: BubbleSheetCardProps) {
  const selected = new Set(value.map((x) => x.toUpperCase()))
  if (mode === 'single') {
    return (
      <RadioGroup value={value[0] || ''} onValueChange={(next) => onChange(next ? [next] : [])} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {options.map((option) => (
          <label
            key={option}
            className={cn(
              'aurora-layout-surface flex cursor-pointer items-center gap-3 rounded-md border p-4 text-sm transition-colors hover:bg-accent',
              selected.has(option) && 'aurora-exam-focus border-primary bg-primary/5'
            )}
          >
            <RadioGroupItem value={option} />
            <span className="font-medium">{option}</span>
          </label>
        ))}
      </RadioGroup>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {options.map((option) => {
        const checked = selected.has(option)
        return (
          <label
            key={option}
            className={cn(
              'aurora-layout-surface flex cursor-pointer items-center gap-3 rounded-md border p-4 text-sm transition-colors hover:bg-accent',
              checked && 'aurora-exam-focus border-primary bg-primary/5'
            )}
          >
            <Checkbox
              checked={checked}
              onCheckedChange={(next) => {
                const out = new Set(selected)
                if (next) out.add(option)
                else out.delete(option)
                onChange(Array.from(out).sort())
              }}
            />
            <span className="font-medium">{option}</span>
          </label>
        )
      })}
    </div>
  )
}
