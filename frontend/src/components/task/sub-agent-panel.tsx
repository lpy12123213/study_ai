import { useState } from "react";
import { CheckCircle2, ChevronRight, CircleAlert, LoaderCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { TOOL_STATUS_META } from "@/features/chat/ui/tool-status";
import { ToolStatusIcon } from "@/features/chat/ui/tool-step";
import type { ToolStepStatus } from "@/features/chat/model/types";
import { formatObservedDuration } from "@/features/chat/ui/format";
import { useTasksStore, type SubAgentRecord, type SubAgentStep } from "@/stores/tasks";

function SubAgentStatusBadge({ status }: { status: SubAgentRecord["status"] }) {
  if (status === "running") {
    return (
      <Badge variant="outline" className="gap-1 text-tool-running">
        <LoaderCircle className="size-3 animate-spin" /> 执行中
      </Badge>
    );
  }
  if (status === "error") {
    return (
      <Badge variant="warning" className="gap-1">
        <CircleAlert className="size-3" /> 失败
      </Badge>
    );
  }
  return (
    <Badge variant="success" className="gap-1">
      <CheckCircle2 className="size-3" /> 已完成
    </Badge>
  );
}

/** 卡片标题：导出子代理固定「导出 · 目标」，检索子代理展示「知识点 · index/total」。 */
function subAgentHeadline(sub: SubAgentRecord): string {
  const kp = sub.kp || "子代理";
  if (sub.kind === "export") return `导出 · ${kp}`;
  const index = sub.index !== undefined ? `${sub.index}` : "";
  const total = sub.total !== undefined ? `/${sub.total}` : "";
  return index ? `${kp} · ${index}${total}` : kp;
}

function SubAgentStepRow({ step }: { step: SubAgentStep }) {
  const status = (step.status in TOOL_STATUS_META ? step.status : "queued") as ToolStepStatus;
  const meta = TOOL_STATUS_META[status];
  const label = step.title || step.name || step.stepId;
  return (
    <li className="flex items-center gap-2 text-xs">
      <ToolStatusIcon status={status} />
      <span className="min-w-0 flex-1 truncate font-medium text-foreground" title={label}>
        {label}
      </span>
      <span className={cn("shrink-0", meta.className)}>{meta.label}</span>
      {step.summary ? <span className="shrink-0 truncate text-muted-foreground">{step.summary}</span> : null}
      {step.elapsedMs !== undefined ? (
        <span className="shrink-0 font-mono text-muted-foreground">{formatObservedDuration(step.elapsedMs)}</span>
      ) : null}
    </li>
  );
}

/** 子代理卡片：折叠标题 + 展开后的嵌套步骤时间线（DetailSection 同款视觉）。 */
function SubAgentCard({ sub }: { sub: SubAgentRecord }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted/60"
      >
        <ChevronRight className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
        <span className="min-w-0 flex-1 truncate font-medium" title={sub.kp}>
          {subAgentHeadline(sub)}
        </span>
        <SubAgentStatusBadge status={sub.status} />
      </button>
      {open ? (
        <div className="border-t border-border px-3 py-2">
          {sub.steps.length === 0 ? (
            <p className="text-xs text-muted-foreground">暂无工具步骤</p>
          ) : (
            <ol className="space-y-1.5">
              {sub.steps.map((step) => (
                <SubAgentStepRow key={step.stepId} step={step} />
              ))}
            </ol>
          )}
        </div>
      ) : null}
    </div>
  );
}

/**
 * 任务中心 · 子代理执行面板：按 subagent_id 分组渲染嵌套工具步骤。
 * 数据来自全局 tasks store（applyEvent 维护的 subagents 记录）；无子代理事件时自隐藏。
 */
export function SubAgentPanel({ taskId, className }: { taskId: string; className?: string }) {
  const subagents = useTasksStore((s) => s.active[taskId]?.subagents);
  const entries = subagents ? Object.entries(subagents) : [];
  if (entries.length === 0) return null;
  return (
    <section aria-label="子代理执行" className={cn("space-y-2", className)}>
      <h4 className="text-xs font-semibold text-muted-foreground">子代理执行</h4>
      {entries.map(([id, sub]) => (
        <SubAgentCard key={id} sub={sub} />
      ))}
    </section>
  );
}
