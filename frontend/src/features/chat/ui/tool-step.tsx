import { cn } from "@/lib/utils";
import type { ToolStepStatus, ToolStepView } from "../model/types";
import { formatObservedDuration } from "./format";
import { TOOL_STATUS_META, toolStatusLabel } from "./tool-status";

export function ToolStatusIcon({ status, className }: { status: ToolStepStatus; className?: string }) {
  const { Icon, className: statusClass } = TOOL_STATUS_META[status];
  return (
    <Icon
      aria-hidden
      className={cn("size-3.5 shrink-0", status === "running" && "animate-spin", statusClass, className)}
    />
  );
}

interface ToolStepProps {
  tool: ToolStepView;
  /** 提供时显示「查看详情」入口（右侧检查器，Phase 4 接入）。 */
  onInspect?: (tool: ToolStepView) => void;
}

function observedDurationMs(tool: ToolStepView): number | undefined {
  if (tool.observedStartAt === undefined || tool.observedResultAt === undefined) return undefined;
  return Math.max(0, tool.observedResultAt - tool.observedStartAt);
}

/** 展示耗时：服务端权威耗时优先，缺失时回退客户端观察耗时。 */
function stepDurationMs(tool: ToolStepView): number | undefined {
  return tool.serverDurationMs ?? observedDurationMs(tool);
}

/** 时间线内的单个工具步骤：名称 + 意图 + 状态 + 一行结果摘要。 */
export function ToolStep({ tool, onInspect }: ToolStepProps) {
  const meta = TOOL_STATUS_META[tool.status];
  const durationMs = stepDurationMs(tool);
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2" data-tool-status={tool.status}>
      <div className="flex items-center gap-2">
        <ToolStatusIcon status={tool.status} />
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">{tool.displayName}</span>
        <span className={cn("shrink-0 text-xs", meta.className)}>{meta.label}</span>
      </div>
      {tool.intent ? <div className="mt-0.5 pl-[22px] text-xs text-muted-foreground">{tool.intent}</div> : null}
      {tool.summary ? (
        <div className="mt-0.5 pl-[22px] text-xs text-muted-foreground">
          {tool.summary}
          {durationMs !== undefined ? ` · ${formatObservedDuration(durationMs)}` : ""}
        </div>
      ) : null}
      {onInspect && (tool.arguments !== undefined || tool.result !== undefined) ? (
        <div className="mt-1 pl-[22px]">
          <button
            type="button"
            onClick={() => onInspect(tool)}
            className="text-xs text-spectral underline-offset-2 transition-colors hover:underline"
          >
            查看详情
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** 单工具行内执行组（紧凑态）：[icon] 名称 · 状态 · 摘要 · 耗时 [查看] */
export function ToolStepInline({ tool, onInspect }: ToolStepProps) {
  const durationMs = stepDurationMs(tool);
  return (
    <div
      className="mb-2 flex max-w-[68ch] items-center gap-2 rounded-full border border-border bg-surface-mist px-3 py-1.5 text-xs"
      data-tool-status={tool.status}
    >
      <ToolStatusIcon status={tool.status} />
      <span className="font-medium text-foreground">{tool.displayName}</span>
      <span className="text-muted-foreground">{toolStatusLabel(tool.status)}</span>
      {tool.summary ? <span className="min-w-0 flex-1 truncate text-muted-foreground">· {tool.summary}</span> : null}
      {durationMs !== undefined ? (
        <span className="shrink-0 font-mono text-muted-foreground">{formatObservedDuration(durationMs)}</span>
      ) : null}
      {onInspect && (tool.arguments !== undefined || tool.result !== undefined) ? (
        <button
          type="button"
          onClick={() => onInspect(tool)}
          className="shrink-0 text-spectral underline-offset-2 transition-colors hover:underline"
        >
          查看
        </button>
      ) : null}
    </div>
  );
}
