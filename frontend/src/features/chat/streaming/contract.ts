/**
 * Chat 流领域事件契约。
 *
 * 输入是 normalizeEvent 归一化后的 TaskEvent（扁平 Chat 事件的 extras 全部落在 data 上），
 * 输出为判别联合。未知类型与缺字段事件返回 null（忽略），不在边界使用 any。
 */
import type { TaskEvent } from "@/shared/api/types";

export type ToolExecutionMode = "parallel" | "sequential";

export type ChatStreamEvent =
  | { kind: "stream_start"; iteration: number; phase?: string }
  | { kind: "text_delta"; content: string; iteration?: number; phase?: string }
  | { kind: "thinking_delta"; content: string; iteration?: number; phase?: string }
  | { kind: "assistant"; content: string; iteration?: number }
  | { kind: "iteration"; round: number; message: string }
  | {
      kind: "tool_start";
      toolCallId: string;
      toolName: string;
      arguments: unknown;
      iteration: number;
      executionMode?: ToolExecutionMode;
    }
  | {
      kind: "tool_result";
      toolCallId: string;
      toolName: string;
      result: unknown;
      iteration: number;
      executionMode?: ToolExecutionMode;
      /** 服务端权威单工具耗时（毫秒）。 */
      serverElapsedMs?: number;
    }
  | { kind: "assistant_final"; content: string; totalIterations?: number; maxReached?: boolean }
  | { kind: "cancelled"; content: string }
  | { kind: "error"; content: string };

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asExecutionMode(value: unknown): ToolExecutionMode | undefined {
  return value === "parallel" || value === "sequential" ? value : undefined;
}

/** 把归一化事件解码为 Chat 领域事件；无法识别时返回 null。 */
export function decodeChatEvent(ev: TaskEvent): ChatStreamEvent | null {
  const d = (ev.data ?? {}) as Record<string, unknown>;
  switch (ev.type) {
    case "stream_start": {
      const iteration = asNumber(d.iteration) ?? 1;
      const phase = asString(d.phase);
      return { kind: "stream_start", iteration, ...(phase ? { phase } : {}) };
    }
    case "text_delta": {
      const content = asString(d.content);
      if (content === undefined) return null;
      const iteration = asNumber(d.iteration);
      const phase = asString(d.phase);
      return {
        kind: "text_delta",
        content,
        ...(iteration !== undefined ? { iteration } : {}),
        ...(phase ? { phase } : {}),
      };
    }
    case "thinking_delta": {
      const content = asString(d.content);
      if (content === undefined) return null;
      const iteration = asNumber(d.iteration);
      const phase = asString(d.phase);
      return {
        kind: "thinking_delta",
        content,
        ...(iteration !== undefined ? { iteration } : {}),
        ...(phase ? { phase } : {}),
      };
    }
    case "assistant": {
      const iteration = asNumber(d.iteration);
      return {
        kind: "assistant",
        content: asString(d.content) ?? "",
        ...(iteration !== undefined ? { iteration } : {}),
      };
    }
    case "iteration": {
      const round = asNumber(d.round);
      if (round === undefined) return null;
      return { kind: "iteration", round, message: asString(d.message) ?? "" };
    }
    case "tool_start": {
      const iteration = asNumber(d.iteration) ?? 1;
      const executionMode = asExecutionMode(d.execution_mode);
      return {
        kind: "tool_start",
        toolCallId: asString(d.tool_call_id) ?? "",
        toolName: asString(d.tool_name) ?? "",
        arguments: d.arguments,
        iteration,
        ...(executionMode ? { executionMode } : {}),
      };
    }
    case "tool_result": {
      const iteration = asNumber(d.iteration) ?? 1;
      const executionMode = asExecutionMode(d.execution_mode);
      const serverElapsedMs = asNumber(d.elapsed_ms);
      return {
        kind: "tool_result",
        toolCallId: asString(d.tool_call_id) ?? "",
        toolName: asString(d.tool_name) ?? "",
        result: d.result,
        iteration,
        ...(executionMode ? { executionMode } : {}),
        ...(serverElapsedMs !== undefined ? { serverElapsedMs } : {}),
      };
    }
    case "assistant_final": {
      const totalIterations = asNumber(d.total_iterations);
      return {
        kind: "assistant_final",
        content: asString(d.content) ?? "",
        ...(totalIterations !== undefined ? { totalIterations } : {}),
        ...(d.max_reached === true ? { maxReached: true } : {}),
      };
    }
    case "cancelled": {
      return { kind: "cancelled", content: asString(d.content) ?? "已按用户要求停止生成。" };
    }
    case "error": {
      return { kind: "error", content: asString(d.content) ?? asString(d.message) ?? "生成失败，请重试" };
    }
    default:
      return null;
  }
}
