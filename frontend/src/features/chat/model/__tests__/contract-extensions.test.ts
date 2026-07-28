/**
 * 契约扩展（后端新增 execution_mode / elapsed_ms / max_reached / cancelled）的
 * 解码与投影测试。旧流（无新字段）不受影响的兼容性同样在此覆盖。
 */
import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeChatEvent } from "../../streaming/contract";
import { chatProjectionReducer, initialChatProjection, type ChatProjectionState } from "../reducer";
import type { ChatStreamEvent } from "../../streaming/contract";

function dispatchEvents(events: ChatStreamEvent[], startAt = 1_000): ChatProjectionState {
  let state = initialChatProjection();
  let at = startAt;
  for (const event of events) {
    state = chatProjectionReducer(state, { type: "event", event, at });
    at += 100;
  }
  return state;
}

function decodeWire(wire: Record<string, unknown>): ChatStreamEvent {
  const normalized = normalizeEvent(wire);
  if (!normalized) throw new Error("normalizeEvent returned null");
  const decoded = decodeChatEvent(normalized);
  if (!decoded) throw new Error("decodeChatEvent returned null");
  return decoded;
}

describe("契约扩展解码", () => {
  it("tool_start 解码 execution_mode；非法值忽略", () => {
    const parallel = decodeWire({
      type: "tool_start",
      tool_call_id: "c1",
      tool_name: "search_questions",
      arguments: {},
      iteration: 1,
      execution_mode: "parallel",
    });
    expect(parallel).toMatchObject({ kind: "tool_start", executionMode: "parallel" });

    const invalid = decodeWire({
      type: "tool_start",
      tool_call_id: "c1",
      tool_name: "search_questions",
      arguments: {},
      iteration: 1,
      execution_mode: "sometimes",
    });
    expect(invalid).not.toHaveProperty("executionMode");
  });

  it("tool_result 解码服务端 elapsed_ms", () => {
    const decoded = decodeWire({
      type: "tool_result",
      tool_call_id: "c1",
      tool_name: "search_questions",
      result: { success: true },
      iteration: 1,
      execution_mode: "sequential",
      elapsed_ms: 843,
    });
    expect(decoded).toMatchObject({ kind: "tool_result", serverElapsedMs: 843, executionMode: "sequential" });
  });

  it("assistant_final 解码结构化 max_reached", () => {
    const decoded = decodeWire({
      type: "assistant_final",
      content: "已完成 10 轮操作。部分结果如下",
      total_iterations: 10,
      max_reached: true,
    });
    expect(decoded).toMatchObject({ kind: "assistant_final", maxReached: true });
  });

  it("cancelled 事件解码", () => {
    const decoded = decodeWire({ type: "cancelled", content: "已按用户要求停止生成。", iteration: 2 });
    expect(decoded).toEqual({ kind: "cancelled", content: "已按用户要求停止生成。" });
  });
});

describe("投影：服务端耗时与并行声明", () => {
  const start: ChatStreamEvent = {
    kind: "tool_start",
    toolCallId: "c1",
    toolName: "search_questions",
    arguments: { keyword: "数列" },
    iteration: 1,
    executionMode: "parallel",
  };
  const start2: ChatStreamEvent = {
    kind: "tool_start",
    toolCallId: "c2",
    toolName: "web_search",
    arguments: { query: "数列" },
    iteration: 1,
    executionMode: "parallel",
  };

  it("tool_start 保存 executionMode；tool_result 保存 serverDurationMs", () => {
    const state = dispatchEvents([
      { kind: "stream_start", iteration: 1, phase: "tool_decision" },
      start,
      start2,
      {
        kind: "tool_result",
        toolCallId: "c1",
        toolName: "search_questions",
        result: { success: true },
        iteration: 1,
        executionMode: "parallel",
        serverElapsedMs: 1200,
      },
    ]);
    const tools = state.turn.iterations[0].tools;
    expect(tools.map((t) => t.executionMode)).toEqual(["parallel", "parallel"]);
    expect(tools[0].serverDurationMs).toBe(1200);
    expect(tools[1].serverDurationMs).toBeUndefined();
  });

  it("无新字段的旧流不产生 executionMode / serverDurationMs", () => {
    const state = dispatchEvents([
      { kind: "stream_start", iteration: 1, phase: "tool_decision" },
      { kind: "tool_start", toolCallId: "c1", toolName: "search_questions", arguments: {}, iteration: 1 },
      { kind: "tool_result", toolCallId: "c1", toolName: "search_questions", result: { success: true }, iteration: 1 },
    ]);
    const tool = state.turn.iterations[0].tools[0];
    expect(tool.executionMode).toBeUndefined();
    expect(tool.serverDurationMs).toBeUndefined();
  });
});

describe("投影：cancelled 终态", () => {
  it("cancelled 把运行中工具标记 stopped，轮次进入 stopped", () => {
    const state = dispatchEvents([
      { kind: "stream_start", iteration: 1, phase: "tool_decision" },
      { kind: "thinking_delta", content: "先检索题目", iteration: 1, phase: "tool_decision" },
      { kind: "tool_start", toolCallId: "c1", toolName: "search_questions", arguments: {}, iteration: 1 },
      { kind: "cancelled", content: "已按用户要求停止生成。" },
    ]);
    expect(state.seenCancelled).toBe(true);
    expect(state.turn.runStatus).toBe("stopped");
    expect(state.turn.iterations[0].status).toBe("stopped");
    expect(state.turn.iterations[0].tools[0].status).toBe("stopped");
    expect(state.turn.thinking?.status).toBe("done");
  });

  it("已完成的工具保持 success，仅未完成的标记 stopped", () => {
    const state = dispatchEvents([
      { kind: "stream_start", iteration: 1, phase: "tool_decision" },
      { kind: "tool_start", toolCallId: "c1", toolName: "search_questions", arguments: {}, iteration: 1 },
      { kind: "tool_start", toolCallId: "c2", toolName: "create_paper", arguments: {}, iteration: 1 },
      { kind: "tool_result", toolCallId: "c1", toolName: "search_questions", result: { success: true }, iteration: 1 },
      { kind: "cancelled", content: "已按用户要求停止生成。" },
    ]);
    const tools = state.turn.iterations[0].tools;
    expect(tools.find((t) => t.id === "c1")?.status).toBe("success");
    expect(tools.find((t) => t.id === "c2")?.status).toBe("stopped");
    expect(state.turn.iterations[0].status).toBe("stopped");
  });

  it("cancelled 后的 settled 只记录终止原因，不改写终态", () => {
    let state = dispatchEvents([
      { kind: "stream_start", iteration: 1, phase: "tool_decision" },
      { kind: "tool_start", toolCallId: "c1", toolName: "search_questions", arguments: {}, iteration: 1 },
      { kind: "cancelled", content: "已按用户要求停止生成。" },
    ]);
    state = chatProjectionReducer(state, { type: "settled", reason: "completed", at: 9_999 });
    expect(state.turn.runStatus).toBe("stopped");
    expect(state.termination).toBe("completed");
  });

  it("cancelled 保留已流式接收的决策文本", () => {
    const state = dispatchEvents([
      { kind: "stream_start", iteration: 1, phase: "tool_decision" },
      { kind: "text_delta", content: "我准备检索数列题目", iteration: 1, phase: "tool_decision" },
      { kind: "cancelled", content: "已按用户要求停止生成。" },
    ]);
    expect(state.turn.finalText).toBe("我准备检索数列题目");
  });
});

describe("投影：结构化 max_reached", () => {
  it("max_reached=true 时即使文案没有固定前缀也标记 maxReached", () => {
    const state = dispatchEvents([
      { kind: "stream_start", iteration: 1 },
      { kind: "assistant_final", content: "阶段性结果如下", totalIterations: 10, maxReached: true },
    ]);
    expect(state.turn.maxReached).toBe(true);
  });

  it("旧流仅有固定前缀文案时仍回退识别", () => {
    const state = dispatchEvents([
      { kind: "stream_start", iteration: 1 },
      { kind: "assistant_final", content: "已完成 10 轮操作。以下是结果", totalIterations: 10 },
    ]);
    expect(state.turn.maxReached).toBe(true);
  });
});
