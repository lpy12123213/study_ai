import { Clock } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ExamTimerProps {
  remainingSeconds: number | null
}

function formatSeconds(seconds: number | null): string {
  if (seconds === null) return '--:--:--'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return [h, m, s].map((x) => String(x).padStart(2, '0')).join(':')
}

export function ExamTimer({ remainingSeconds }: ExamTimerProps) {
  const danger = remainingSeconds !== null && remainingSeconds <= 60
  const warning = remainingSeconds !== null && remainingSeconds > 60 && remainingSeconds <= 300
  return (
    <div
      className={cn(
        'inline-flex min-w-32 items-center justify-center gap-2 rounded-md border px-3 py-2 font-mono text-sm',
        warning && 'border-amber-300 bg-amber-50 text-amber-700',
        danger && 'animate-pulse border-red-300 bg-red-50 text-red-700'
      )}
    >
      <Clock className="h-4 w-4" />
      {formatSeconds(remainingSeconds)}
    </div>
  )
}
