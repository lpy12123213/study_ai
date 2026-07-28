import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { selectCompactTool, selectIterationDurationMs, selectVisibleIterations } from "../model/selectors";
import type { ConversationTurnView, ToolIterationView, ToolStepView } from "../model/types";
import { formatObservedDuration } from "./format";
import { toolStatusLabel } from "./tool-status";
import { ToolStatusIcon, ToolStep, ToolStepInline } from "./tool-step";

interface IterationTimelineProps {
  turn: ConversationTurnView;
  onInspectTool?: (tool: ToolStepView) => void;
}

const ITERATION_STATUS_LABEL: Record<ToolIterationView["status"], string> = {
  queued: "等待中",
  running: "执行中",
  success: "已完成",
  error: "有工具失败",
  interrupted: "已停止接收",
  stopped: "已停止",
};

function iterationHeadline(it: ToolIterationView): string {
  const durationMs = selectIterationDurationMs(it);
  const parts = [it.label, ITERATION_STATUS_LABEL[it.status]];
  if (durationMs !== undefined && it.status !== "running" && it.status !== "queued") {
    parts.push(formatObservedDuration(durationMs));
  }
  return parts.join(" · ");
}

/** 服务端声明的同轮执行方式：全部工具一致且 ≥2 个时才宣称（缺字段的旧流不宣称）。 */
function iterationExecutionMode(it: ToolIterationView): "parallel" | "sequential" | undefined {
  if (it.tools.length < 2) return undefined;
  const mode = it.tools[0]?.executionMode;
  if (!mode) return undefined;
  return it.tools.every((t) => t.executionMode === mode) ? mode : undefined;
}

function IterationBlock({
  iteration,
  defaultOpen,
  onInspectTool,
}: {
  iteration: ToolIterationView;
  defaultOpen: boolean;
  onInspectTool?: (tool: ToolStepView) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const running = iteration.status === "running" || iteration.status === "queued";
  const executionMode = iterationExecutionMode(iteration);
  return (
    <div className="relative pl-5" data-iteration-status={iteration.status}>
      {/* 时间线标记与连接线（连接线不承担唯一语义，文字同时表达） */}
      <span
        aria-hidden
        className={cn(
          "absolute left-0 top-[7px] size-2 rounded-full border-2",
          running ? "border-timeline-marker bg-timeline-marker/30" : "border-timeline-rail bg-transparent",
          iteration.status === "error" && "border-tool-error",
          iteration.status === "success" && "border-tool-success",
        )}
      />
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-left text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        <ToolStatusIcon status={iteration.status} />
        {iterationHeadline(iteration)}
        {executionMode ? (
          <span className="rounded-full border border-border bg-surface-mist px-1.5 py-px text-[11px] font-normal">
            {executionMode === "parallel" ? "并行执行" : "顺序执行"}
          </span>
        ) : null}
      </button>
      {open ? (
        executionMode === "parallel" ? (
          // 并行分支线（§7.5）：一条分支主线并列承载同轮工具，不画成先后串行
          <div className="relative mt-2 space-y-1.5 pl-3">
            <span aria-hidden className="absolute bottom-3 left-0 top-3 w-0.5 rounded-full bg-timeline-marker/50" />
            {iteration.tools.map((tool) => (
              <div key={tool.id} className="relative">
                <span aria-hidden className="absolute -left-3 top-1/2 h-px w-3 bg-timeline-marker/50" />
                <ToolStep tool={tool} {...(onInspectTool ? { onInspect: onInspectTool } : {})} />
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-2 space-y-1.5">
            {iteration.tools.map((tool) => (
              <ToolStep key={tool.id} tool={tool} {...(onInspectTool ? { onInspect: onInspectTool } : {})} />
            ))}
          </div>
        )
      ) : (
        <div className="mt-0.5 pl-[26px] text-xs text-muted-foreground">
          {iteration.tools.map((t) => t.displayName).join("、")}
          {iteration.tools.length > 0 ? `（${iteration.tools.length} 个工具 · ${toolStatusLabel(iteration.status)}）` : ""}
        </div>
      )}
    </div>
  );
}

/**
 * 轮次时间线（方案 2）。
 * - 单工具自动收缩为行内执行组。
 * - 当前（最新）iteration 默认展开，已完成 iteration 默认折叠为一行摘要。
 * - 服务端 execution_mode 声明并行时以分支线并列表达；缺字段的旧流不宣称并行关系。
 * - 单工具耗时优先展示服务端 elapsed_ms 权威值，缺失时回退客户端观察时间。
 */
export function IterationTimeline({ turn, onInspectTool }: IterationTimelineProps) {
  const visible = selectVisibleIterations(turn);
  if (visible.length === 0) return null;

  const compactTool = selectCompactTool(turn);
  if (compactTool) {
    return (
      <div aria-live="polite">
        <ToolStepInline tool={compactTool} {...(onInspectTool ? { onInspect: onInspectTool } : {})} />
      </div>
    );
  }

  const lastIndex = visible[visible.length - 1]?.index;
  return (
    <section aria-label="工具执行时间线" aria-live="polite" className="mb-3 max-w-[68ch]">
      <div className="relative rounded-xl border border-border bg-surface px-3.5 py-3">
        <span aria-hidden className="absolute bottom-4 left-[7px] top-4 w-px bg-timeline-rail" />
        <div className="space-y-3">
          {visible.map((it) => (
            <IterationBlock
              key={it.index}
              iteration={it}
              defaultOpen={it.index === lastIndex}
              {...(onInspectTool ? { onInspectTool } : {})}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
