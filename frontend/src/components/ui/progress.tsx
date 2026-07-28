import * as React from "react";

import { cn } from "@/lib/utils";
import { clamp } from "@/lib/format";

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: number | null;
  indeterminate?: boolean;
}

const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value, indeterminate, ...props }, ref) => {
    const pct = clamp(value ?? 0, 0, 100);
    return (
      <div
        ref={ref}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={indeterminate ? undefined : Math.round(pct)}
        className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
        {...props}
      >
        <div
          className={cn(
            "h-full rounded-full bg-primary transition-[width] duration-300 ease-out",
            indeterminate && "w-1/3 animate-pulse",
          )}
          style={indeterminate ? undefined : { width: `${pct}%` }}
        />
      </div>
    );
  },
);
Progress.displayName = "Progress";

export { Progress };
