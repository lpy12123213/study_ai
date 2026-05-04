import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground shadow-none hover:bg-[var(--study-primary-active)]",
        secondary:
          "border-border bg-secondary text-secondary-foreground hover:bg-accent",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground shadow-none hover:bg-destructive/80",
        outline: "text-foreground",
        success:
          "border-border/60 bg-secondary text-secondary-foreground hover:bg-secondary/80",
        warning:
          "border-border/60 bg-secondary text-secondary-foreground hover:bg-secondary/80",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge }
