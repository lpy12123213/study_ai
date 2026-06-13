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
        'aurora-brand-mark relative inline-flex items-center justify-center rounded-md',
        'bg-primary text-primary-foreground',
        className
      )}
      style={{ width: size, height: size }}
    >
      <Sparkles
        className="relative"
        style={{ width: size * 0.6, height: size * 0.6 }}
        strokeWidth={2}
      />
    </div>
  )
}
