import type { ReactNode } from "react";
import { Square, Unplug, XCircle } from "lucide-react";

import { Spinner } from "@/components/ui/spinner";
import type { ConversationTurnView, ToolStepView } from "../model/types";
import { IterationTimeline } from "./iteration-timeline";
import { ThinkingText } from "./thinking-text";

interface AssistantTurnProps {
  turn: ConversationTurnView;
  /** 历史轮思考文本默认折叠；当前轮默认展开。 */
  current?: boolean;
  /** 最终答案区域（MarkdownView、流式光标等由页面装配）。 */
  children?: ReactNode;
  onInspectTool?: (tool: ToolStepView) => void;
}

/**
 * 一个助手轮次：思考文本 → 工具时间线 → 最终答案（视觉规划 §7.2）。
 * 三个层级独立渲染，不合并为一段连续 Markdown。
 */
export function AssistantTurn({ turn, current = false, children, onInspectTool }: AssistantTurnProps) {
  const streaming = turn.runStatus === "streaming";
  const hasContent = Boolean(turn.finalText || turn.interimText);
  return (
    <div data-run-status={turn.runStatus}>
      {turn.thinking ? <ThinkingText thinking={turn.thinking} defaultExpanded={current} /> : null}

      <IterationTimeline turn={turn} {...(onInspectTool ? { onInspectTool } : {})} />

      {children}

      {!hasContent && streaming ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> 正在思考…
        </div>
      ) : null}

      {turn.runStatus === "interrupted" ? (
        <div role="status" className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Unplug className="size-3.5" />
          已停止接收，以上内容可能不完整；服务端工具可能仍会执行完成。
        </div>
      ) : null}

      {turn.runStatus === "stopped" ? (
        <div role="status" className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Square className="size-3.5" />
          任务已停止：服务端已确认取消，未开始的工具不再执行。
        </div>
      ) : null}

      {turn.runStatus === "error" && turn.errorMessage ? (
        <div role="alert" className="mt-2 flex items-center gap-1.5 text-sm text-tool-error">
          <XCircle className="size-4 shrink-0" />
          失败：{turn.errorMessage}
        </div>
      ) : null}

      {turn.maxReached ? (
        <div role="status" className="mt-2 text-xs text-warning">
          已达到最大操作轮数，以上为当前已完成的阶段性结果。
        </div>
      ) : null}
    </div>
  );
}
