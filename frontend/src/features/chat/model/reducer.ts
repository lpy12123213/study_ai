/**
 * Chat 事件 → ConversationTurnView 的纯投影 reducer。
 *
 * 不持有连接对象、不发起 fetch、不显示 toast；输入事件 + 到达时间，输出新状态。
 * 时间均为客户端观察时间（非服务端权威耗时）。
 *
 * 关键契约（2026-07-26 核对 backend/workspace/chat/service.py）：
 * - 工具决策阶段的 text_delta/thinking_delta 携带 phase:"tool_decision"；
 *   最终回答阶段的 text_delta 不带 phase，且不保证携带 iteration。
 * - 决策轮完整文本由 assistant 事件覆盖去重；最终回答全文以 assistant_final.content 为准。
 * - 首轮无 iteration 事件，由 stream_start 隐式开启；第 2 轮起发送 iteration 事件。
 * - 整批 tool_start 先发，执行结束后集中发 tool_result；wire 不携带并行/耗时字段。
 * - error 为终态事件；[DONE]/EOF/Abort 是 transport 语义，经 settled 动作进入。
 */
import type { ChatStreamEvent } from "../streaming/contract";
import { summarizeToolResult, toolDisplayName, toolIntent, toolResultFailed } from "./tool-result-adapters";
import type { ConversationTurnView, ToolIterationView, ToolStepView } from "./types";

export type StreamEndReason = "completed" | "eof" | "aborted" | "error";

export type ChatProjectionAction =
  | { type: "reset" }
  | { type: "event"; event: ChatStreamEvent; at: number }
  | { type: "stop_requested"; at: number }
  | { type: "settled"; reason: StreamEndReason; at: number; error?: Error };

export interface ChatProjectionState {
  turn: ConversationTurnView;
  /** 当前决策轮文本流（新 iteration 的首个 stream_start 到达时重置；同轮重复 stream_start 不重置）。 */
  decisionText: string;
  /** 最终回答文本流（不带 phase 的 text_delta 累积）。 */
  answerText: string;
  /** 首个 thinking_delta 的到达时间，用于计算客户端观察耗时。 */
  thinkingStartedAt?: number;
  /** 最近一次 stream_start 的 iteration，用于识别新一轮决策段。 */
  lastStreamIteration: number;
  seenFinal: boolean;
  seenError: boolean;
  /** 已收到服务端取消确认（cancelled 事件）。 */
  seenCancelled: boolean;
  stopIntent: boolean;
  termination?: StreamEndReason;
}

export function initialChatProjection(): ChatProjectionState {
  return {
    turn: {
      runStatus: "idle",
      interimText: "",
      iterations: [],
      finalText: "",
    },
    decisionText: "",
    answerText: "",
    lastStreamIteration: 0,
    seenFinal: false,
    seenError: false,
    seenCancelled: false,
    stopIntent: false,
  };
}

/** 后端在达到最大轮数时没有结构化字段，唯一信号是 assistant_final.content 的固定前缀。 */
const MAX_REACHED_RE = /^已完成\s*\d+\s*轮操作。/;

function syncInterim(state: ChatProjectionState): ChatProjectionState {
  if (state.turn.finalText) return state;
  const interim = state.answerText || state.decisionText;
  if (interim === state.turn.interimText) return state;
  return { ...state, turn: { ...state.turn, interimText: interim } };
}

function getOrCreateIteration(turn: ConversationTurnView, index: number): ConversationTurnView {
  if (turn.iterations.some((it) => it.index === index)) return turn;
  const created: ToolIterationView = { index, label: `第 ${index} 轮`, status: "queued", tools: [] };
  return { ...turn, iterations: [...turn.iterations, created].sort((a, b) => a.index - b.index) };
}

function patchIteration(
  turn: ConversationTurnView,
  index: number,
  patch: (it: ToolIterationView) => ToolIterationView,
): ConversationTurnView {
  return { ...turn, iterations: turn.iterations.map((it) => (it.index === index ? patch(it) : it)) };
}

function patchTool(
  turn: ConversationTurnView,
  toolCallId: string,
  patch: (t: ToolStepView) => ToolStepView,
): ConversationTurnView {
  return {
    ...turn,
    iterations: turn.iterations.map((it) => ({
      ...it,
      tools: it.tools.map((t) => (t.id === toolCallId ? patch(t) : t)),
    })),
  };
}

/** 全部工具有结果后收尾 iteration：状态聚合 + 完成时间。 */
function finalizeIterationIfComplete(it: ToolIterationView): ToolIterationView {
  if (it.tools.length === 0) return it;
  const pending = it.tools.some((t) => t.status === "running" || t.status === "queued");
  if (pending) return it;
  const anyError = it.tools.some((t) => t.status === "error");
  const anyInterrupted = it.tools.some((t) => t.status === "interrupted");
  const anyStopped = it.tools.some((t) => t.status === "stopped");
  const status: ToolIterationView["status"] = anyError
    ? "error"
    : anyInterrupted
      ? "interrupted"
      : anyStopped
        ? "stopped"
        : "success";
  const completedAt = Math.max(...it.tools.map((t) => t.observedResultAt ?? 0)) || it.completedAt;
  return { ...it, status, ...(completedAt ? { completedAt } : {}) };
}

function markThinkingDone(state: ChatProjectionState, at: number): ChatProjectionState {
  const thinking = state.turn.thinking;
  if (!thinking || thinking.status === "done") return state;
  const durationMs = state.thinkingStartedAt !== undefined ? Math.max(0, at - state.thinkingStartedAt) : undefined;
  return {
    ...state,
    turn: {
      ...state.turn,
      thinking: { ...thinking, status: "done", ...(durationMs !== undefined ? { durationMs } : {}) },
    },
  };
}

/** 把仍在 running/queued 的 iteration 与 tool 标记为给定终态。 */
function markActiveNodes(
  state: ChatProjectionState,
  status: "error" | "interrupted" | "stopped",
  at: number,
): ChatProjectionState {
  const iterations = state.turn.iterations.map((it) => {
    if (it.status !== "running" && it.status !== "queued") return it;
    const tools = it.tools.map((t) =>
      t.status === "running" || t.status === "queued"
        ? { ...t, status, observedResultAt: t.observedResultAt ?? at }
        : t,
    );
    return finalizeIterationIfComplete({ ...it, tools, status, completedAt: it.completedAt ?? at });
  });
  return { ...state, turn: { ...state.turn, iterations } };
}

function applyEvent(state: ChatProjectionState, event: ChatStreamEvent, at: number): ChatProjectionState {
  const turn = state.turn;
  switch (event.kind) {
    case "stream_start": {
      // 新 iteration 的首个 stream_start 开启新文本段（决策段或最终回答段），重置决策文本；
      // 同轮重复出现的 stream_start 不重置已投影内容（thinking / 工具时间线 / 文本均保留）。
      const isNewSegment = event.iteration > state.lastStreamIteration;
      const next: ChatProjectionState = {
        ...state,
        turn: { ...turn, runStatus: "streaming" },
        lastStreamIteration: Math.max(state.lastStreamIteration, event.iteration),
        ...(isNewSegment ? { decisionText: "" } : {}),
      };
      return syncInterim(next);
    }

    case "thinking_delta": {
      const thinking = turn.thinking
        ? { ...turn.thinking, text: turn.thinking.text + event.content, status: "streaming" as const }
        : { text: event.content, status: "streaming" as const, userVisible: true as const };
      return {
        ...state,
        turn: { ...turn, runStatus: "streaming", thinking },
        thinkingStartedAt: state.thinkingStartedAt ?? at,
      };
    }

    case "text_delta": {
      if (event.phase === undefined) {
        // 最终回答段。若决策文本尚未并入回答（assistant_final 前的 remaining 场景），先并入再追加。
        const base = state.answerText || state.decisionText;
        const next: ChatProjectionState = {
          ...state,
          decisionText: "",
          answerText: base + event.content,
          turn: { ...turn, runStatus: "streaming" },
        };
        return syncInterim(next);
      }
      // 决策阶段文本
      const next: ChatProjectionState = {
        ...state,
        decisionText: state.decisionText + event.content,
        turn: { ...turn, runStatus: "streaming" },
      };
      return syncInterim(next);
    }

    case "assistant": {
      // 工具决策轮完整文本：覆盖去重已流式的决策段
      const next: ChatProjectionState = {
        ...state,
        decisionText: event.content || state.decisionText,
        turn: { ...turn, runStatus: "streaming" },
      };
      return syncInterim(next);
    }

    case "iteration": {
      // 新一轮开始：此前仍在 running 的更早 iteration 按后端保证已结束
      let nextTurn: ConversationTurnView = {
        ...turn,
        runStatus: "streaming",
        iterations: turn.iterations.map((it) =>
          it.status === "running" && it.index < event.round
            ? finalizeIterationIfComplete({ ...it, status: "success", completedAt: it.completedAt ?? at })
            : it,
        ),
      };
      nextTurn = getOrCreateIteration(nextTurn, event.round);
      nextTurn = patchIteration(nextTurn, event.round, (it) => ({
        ...it,
        label: `第 ${event.round} 轮`,
        status: it.status === "queued" ? "running" : it.status,
      }));
      return { ...state, turn: nextTurn };
    }

    case "tool_start": {
      let nextTurn = getOrCreateIteration(turn, event.iteration);
      const siblingCount = nextTurn.iterations.find((i) => i.index === event.iteration)?.tools.length ?? 0;
      const step: ToolStepView = {
        id: event.toolCallId || `tool-${event.iteration}-${siblingCount}`,
        iteration: event.iteration,
        name: event.toolName,
        displayName: toolDisplayName(event.toolName),
        intent: toolIntent(event.toolName, event.arguments),
        status: "running",
        arguments: event.arguments,
        observedStartAt: at,
        ...(event.executionMode ? { executionMode: event.executionMode } : {}),
      };
      nextTurn = patchIteration(nextTurn, event.iteration, (it) => ({
        ...it,
        status: "running",
        startedAt: it.startedAt ?? at,
        tools: it.tools.some((t) => t.id === step.id) ? it.tools : [...it.tools, step],
      }));
      return { ...state, turn: { ...nextTurn, runStatus: "streaming" } };
    }

    case "tool_result": {
      const failed = toolResultFailed(event.result);
      let nextTurn = patchTool(turn, event.toolCallId, (t) => ({
        ...t,
        status: failed ? ("error" as const) : ("success" as const),
        result: event.result,
        summary: summarizeToolResult(event.toolName || t.name, event.result),
        observedResultAt: at,
        ...(event.serverElapsedMs !== undefined ? { serverDurationMs: event.serverElapsedMs } : {}),
        ...(event.executionMode && !t.executionMode ? { executionMode: event.executionMode } : {}),
      }));
      const owner = nextTurn.iterations.find((it) => it.tools.some((t) => t.id === event.toolCallId));
      if (owner) {
        nextTurn = patchIteration(nextTurn, owner.index, finalizeIterationIfComplete);
      }
      return { ...state, turn: nextTurn };
    }

    case "assistant_final": {
      let next: ChatProjectionState = {
        ...state,
        seenFinal: true,
        turn: {
          ...turn,
          runStatus: "done",
          finalText: event.content || state.answerText || state.decisionText,
          // 优先使用服务端结构化 max_reached 字段；旧流回退固定文案前缀识别
          maxReached: event.maxReached || MAX_REACHED_RE.test(event.content) ? true : undefined,
          iterations: turn.iterations.map((it) =>
            it.status === "running" || it.status === "queued"
              ? finalizeIterationIfComplete({ ...it, status: "success", completedAt: it.completedAt ?? at })
              : it,
          ),
        },
      };
      next = markThinkingDone(next, at);
      return next;
    }

    case "cancelled": {
      // 服务端取消确认（§9.2 增加取消契约后）：活动工具标记 stopped，轮次进入 stopped 终态
      let next: ChatProjectionState = {
        ...state,
        seenCancelled: true,
        turn: {
          ...turn,
          runStatus: "stopped",
          finalText: turn.finalText || state.answerText || state.decisionText,
        },
      };
      next = markActiveNodes(next, "stopped", at);
      next = markThinkingDone(next, at);
      return next;
    }

    case "error": {
      let next: ChatProjectionState = {
        ...state,
        seenError: true,
        turn: { ...turn, runStatus: "error", errorMessage: event.content },
      };
      next = markActiveNodes(next, "error", at);
      next = markThinkingDone(next, at);
      return next;
    }

    default:
      return state;
  }
}

function applySettled(
  state: ChatProjectionState,
  reason: StreamEndReason,
  at: number,
  error?: Error,
): ChatProjectionState {
  // 已有终态结论（final/error/cancelled）：transport 收尾只记录原因
  if (state.seenFinal || state.seenError || state.seenCancelled) {
    return { ...state, termination: reason };
  }
  let next: ChatProjectionState = { ...state, termination: reason };
  if (reason === "error") {
    next = {
      ...next,
      turn: {
        ...next.turn,
        runStatus: "error",
        errorMessage: error instanceof Error ? error.message : "网络连接失败，请检查后端服务",
      },
    };
    // 传输失败时工具真实状态未知：标记 interrupted 而非 error
    next = markActiveNodes(next, "interrupted", at);
  } else {
    // aborted / 无 final 的 completed 或 eof：已收到的内容保留并标记中断
    next = { ...next, turn: { ...next.turn, runStatus: "interrupted" } };
    next = markActiveNodes(next, "interrupted", at);
  }
  next = markThinkingDone(next, at);
  return next;
}

export function chatProjectionReducer(
  state: ChatProjectionState,
  action: ChatProjectionAction,
): ChatProjectionState {
  switch (action.type) {
    case "reset":
      return initialChatProjection();
    case "event":
      // 终态后到达的事件（如 transport 收尾阶段的残留帧）不再改变投影
      if (state.seenFinal || state.seenError || state.seenCancelled) return state;
      return applyEvent(state, action.event, action.at);
    case "stop_requested":
      return { ...state, stopIntent: true };
    case "settled":
      return applySettled(state, action.reason, action.at, action.error);
    default:
      return state;
  }
}
