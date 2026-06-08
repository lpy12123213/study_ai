import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

interface StartExamDialogProps {
  open: boolean
  isPending?: boolean
  onOpenChange: (open: boolean) => void
  onStart: (payload: { mode: 'timed' | 'untimed'; timeLimitMinutes: number | null }) => void
}

export function StartExamDialog({ open, isPending, onOpenChange, onStart }: StartExamDialogProps) {
  const [mode, setMode] = useState<'timed' | 'untimed'>('untimed')
  const [timeLimitText, setTimeLimitText] = useState('90')

  useEffect(() => {
    if (!open) return
    setMode('untimed')
    setTimeLimitText('90')
  }, [open])

  const timeLimitMinutes = Math.max(1, Math.min(1440, Number(timeLimitText) || 90))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>开始答题</DialogTitle>
          <DialogDescription>选择练习或限时考试模式。</DialogDescription>
        </DialogHeader>
        <RadioGroup value={mode} onValueChange={(value) => setMode(value === 'timed' ? 'timed' : 'untimed')}>
          <label className="flex cursor-pointer items-center gap-3 rounded-md border p-3">
            <RadioGroupItem value="untimed" />
            <span className="text-sm">不限时练习</span>
          </label>
          <label className="flex cursor-pointer items-center gap-3 rounded-md border p-3">
            <RadioGroupItem value="timed" />
            <span className="text-sm">限时考试</span>
          </label>
        </RadioGroup>
        {mode === 'timed' && (
          <Input
            type="number"
            min={1}
            max={1440}
            value={timeLimitText}
            onChange={(event) => setTimeLimitText(event.target.value)}
            onBlur={() => setTimeLimitText(String(timeLimitMinutes))}
          />
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            type="button"
            onClick={() => onStart({ mode, timeLimitMinutes: mode === 'timed' ? timeLimitMinutes : null })}
            disabled={isPending}
          >
            {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            开始
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
