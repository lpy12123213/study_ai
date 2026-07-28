/**
 * ConversationTurnView 的派生选择器：UI 只读这些函数，不自行遍历内部结构。
 */
import type { ChatProjectionState } from "./reducer";
import type { ConversationTurnView, ToolIterationView, ToolStepView } from "./types";

/** 主正文：最终答案优先，其次流式中的可见文本。 */
export function selectVisibleText(turn: ConversationTurnView): string {
  return turn.finalText || turn.interimText;
}

/** 有工具的时间线条目（隐藏无工具的空轮次）。 */
export function selectVisibleIterations(turn: ConversationTurnView): ToolIterationView[] {
  return turn.iterations.filter((it) => it.tools.length > 0);
}

/** 全部工具步骤（按轮次顺序展开）。 */
export function selectAllTools(turn: ConversationTurnView): ToolStepView[] {
  return turn.iterations.flatMap((it) => it.tools);
}

/**
 * 单工具紧凑态：整个轮次只有一个工具时成立（视觉规划 §7.3 行内执行组）。
 * 是否有并行/多轮由结构决定；耗时展示仍受当前契约限制（仅客户端观察时间）。
 */
export function selectCompactTool(turn: ConversationTurnView): ToolStepView | null {
  const visible = selectVisibleIterations(turn);
  if (visible.length !== 1) return null;
  if (visible[0].tools.length !== 1) return null;
  return visible[0].tools[0];
}

/** 时间线聚合状态：用于 aria-live 摘要。 */
export function selectTimelineSummary(turn: ConversationTurnView): string {
  const tools = selectAllTools(turn);
  if (tools.length === 0) return "";
  const running = tools.filter((t) => t.status === "running").length;
  const failed = tools.filter((t) => t.status === "error").length;
  const done = tools.filter((t) => t.status === "success").length;
  if (running > 0) return `工具执行中：共 ${tools.length} 个，已完成 ${done} 个`;
  if (failed > 0) return `工具执行完成：共 ${tools.length} 个，${failed} 个失败`;
  return `工具执行完成：共 ${tools.length} 个`;
}

/** iteration 的客户端观察耗时（毫秒）；缺少时间戳时返回 undefined。 */
export function selectIterationDurationMs(it: ToolIterationView): number | undefined {
  if (it.startedAt === undefined || it.completedAt === undefined) return undefined;
  return Math.max(0, it.completedAt - it.startedAt);
}

/** 轮次是否仍在流式进行中。 */
export function selectIsStreaming(state: ChatProjectionState): boolean {
  return state.turn.runStatus === "streaming";
}

/** 检查器概览统计：工具数、成败计数、当前 iteration 与客户端观察耗时跨度。 */
export interface ToolStats {
  total: number;
  running: number;
  success: number;
  error: number;
  interrupted: number;
  /** 仍在执行的 iteration 序号；无运行中工具时为最后一轮。 */
  currentIteration?: number;
  /** 首个 tool_start 到最后 tool_result 的观察跨度（毫秒）；不足时 undefined。 */
  observedSpanMs?: number;
}

export function selectToolStats(turn: ConversationTurnView): ToolStats {
  const tools = selectAllTools(turn);
  const starts = tools.map((t) => t.observedStartAt).filter((v): v is number => v !== undefined);
  const ends = tools.map((t) => t.observedResultAt).filter((v): v is number => v !== undefined);
  const runningIteration = turn.iterations.find((it) => it.status === "running")?.index;
  const lastIteration = turn.iterations.length > 0 ? turn.iterations[turn.iterations.length - 1].index : undefined;
  return {
    total: tools.length,
    running: tools.filter((t) => t.status === "running" || t.status === "queued").length,
    success: tools.filter((t) => t.status === "success").length,
    error: tools.filter((t) => t.status === "error").length,
    interrupted: tools.filter((t) => t.status === "interrupted").length,
    currentIteration: runningIteration ?? lastIteration,
    observedSpanMs:
      starts.length > 0 && ends.length > 0 ? Math.max(0, Math.max(...ends) - Math.min(...starts)) : undefined,
  };
}
