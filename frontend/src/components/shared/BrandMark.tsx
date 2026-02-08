import { Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

interface BrandMarkProps {
  size?: number
  className?: string
}

export function BrandMark({ size = 32, className }: BrandMarkProps) {
  return (
    <div
      className={cn(
        'relative inline-flex items-center justify-center rounded-xl',
        'bg-foreground text-background',
        'shadow-sm ring-1 ring-border/60',
        className
      )}
      style={{ width: size, height: size }}
    >
      <div className="absolute inset-0 rounded-xl bg-[radial-gradient(circle_at_30%_30%,rgba(255,255,255,0.20),transparent_55%)] dark:bg-[radial-gradient(circle_at_30%_30%,rgba(0,0,0,0.10),transparent_55%)]" />
      <Sparkles
        className="relative text-background"
        style={{ width: size * 0.55, height: size * 0.55 }}
        strokeWidth={1.8}
      />
    </div>
  )
}

