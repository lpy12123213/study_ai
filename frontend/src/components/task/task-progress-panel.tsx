import { useTasksStore } from "@/stores/tasks";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { StepTimeline } from "@/components/task/step-timeline";
import { TASK_STATUS_LABELS } from "@/shared/api/types";
import { cn } from "@/lib/utils";

/**
 * 任务进度面板：进度条 + 状态文案 + 步骤时间线。
 * 数据来自全局 tasks store（streamTask 推送）。
 */
export function TaskProgressPanel({
  taskId,
  className,
  showSteps = true,
}: {
  taskId: string;
  className?: string;
  showSteps?: boolean;
}) {
  const task = useTasksStore((s) => s.active[taskId]);
  if (!task) return null;
  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center gap-3">
        <Progress value={task.progress} className="h-1.5 flex-1" />
        <span className="w-10 text-right text-xs tabular-nums text-muted-foreground">
          {Math.round(task.progress)}%
        </span>
        <Badge variant={task.status === "failed" ? "destructive" : task.status === "completed" ? "success" : task.status === "pending_review" ? "warning" : "muted"}>
          {TASK_STATUS_LABELS[task.status] ?? task.status}
        </Badge>
      </div>
      {task.statusText ? <div className="text-xs text-muted-foreground">{task.statusText}</div> : null}
      {showSteps && task.steps.length > 0 ? <StepTimeline steps={task.steps} /> : null}
    </div>
  );
}
