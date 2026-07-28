import { CheckCircle2, CircleDot, Loader2, PauseCircle, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import type { TaskStep } from "@/shared/api/types";

const STATUS_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  completed: CheckCircle2,
  running: Loader2,
  failed: XCircle,
  paused: PauseCircle,
  pending_review: PauseCircle,
};

const STATUS_STYLE: Record<string, string> = {
  completed: "text-success",
  running: "text-primary animate-spin",
  failed: "text-destructive",
  paused: "text-warning",
  pending_review: "text-warning",
};

/** 任务步骤时间线（step 事件流的可视化）。 */
export function StepTimeline({ steps, className }: { steps: TaskStep[]; className?: string }) {
  if (steps.length === 0) return null;
  return (
    <ol className={cn("relative space-y-3", className)}>
      {steps.map((step, i) => {
        const Icon = STATUS_ICON[step.status] ?? CircleDot;
        const isLast = i === steps.length - 1;
        return (
          <li key={step.id ?? i} className="relative flex gap-3 pl-0.5">
            {!isLast ? <span className="absolute left-[9px] top-6 h-[calc(100%-12px)] w-px bg-border" /> : null}
            <Icon className={cn("mt-0.5 size-[18px] shrink-0", STATUS_STYLE[step.status] ?? "text-muted-foreground")} />
            <div className="min-w-0 flex-1 pb-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{step.title || step.id}</span>
                {step.toolName ? (
                  <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {step.toolName}
                  </span>
                ) : null}
              </div>
              {step.error ? <div className="mt-0.5 text-xs text-destructive">{step.error}</div> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
