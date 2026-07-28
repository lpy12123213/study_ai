import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeChatEvent } from "../../streaming/contract";

function decode(raw: Record<string, unknown>) {
  const normalized = normalizeEvent(raw);
  if (!normalized) throw new Error("normalizeEvent returned null");
  return decodeChatEvent(normalized);
}

describe("decodeChatEvent", () => {
  it("stream_start：保留 iteration 与 phase，缺省 iteration 为 1", () => {
    expect(decode({ type: "stream_start", iteration: 2, phase: "tool_decision" })).toEqual({
      kind: "stream_start",
      iteration: 2,
      phase: "tool_decision",
    });
    expect(decode({ type: "stream_start" })).toEqual({ kind: "stream_start", iteration: 1 });
  });

  it("text_delta / thinking_delta：保留 phase（区分决策段与最终回答段）", () => {
    expect(decode({ type: "text_delta", content: "a", iteration: 1, phase: "tool_decision" })).toEqual({
      kind: "text_delta",
      content: "a",
      iteration: 1,
      phase: "tool_decision",
    });
    expect(decode({ type: "thinking_delta", content: "想" })).toEqual({ kind: "thinking_delta", content: "想" });
  });

  it("tool_start / tool_result：保留 arguments / result 与 iteration", () => {
    expect(
      decode({ type: "tool_start", tool_call_id: "c1", tool_name: "web_search", arguments: { query: "x" }, iteration: 3 }),
    ).toEqual({ kind: "tool_start", toolCallId: "c1", toolName: "web_search", arguments: { query: "x" }, iteration: 3 });
    expect(decode({ type: "tool_result", tool_call_id: "c1", tool_name: "web_search", result: { success: true } })).toEqual({
      kind: "tool_result",
      toolCallId: "c1",
      toolName: "web_search",
      result: { success: true },
      iteration: 1,
    });
  });

  it("iteration：使用 round 字段", () => {
    expect(decode({ type: "iteration", round: 2, message: "AI 正在进行第 2 轮操作..." })).toEqual({
      kind: "iteration",
      round: 2,
      message: "AI 正在进行第 2 轮操作...",
    });
  });

  it("error：content 缺失时回退 message，再回退默认文案", () => {
    expect(decode({ type: "error", content: "api_error" })).toEqual({ kind: "error", content: "api_error" });
    expect(decode({ type: "error", message: "boom" })).toEqual({ kind: "error", content: "boom" });
    expect(decode({ type: "error" })).toEqual({ kind: "error", content: "生成失败，请重试" });
  });

  it("未知类型或缺字段事件返回 null", () => {
    expect(decode({ type: "ping" })).toBeNull();
    expect(decode({ type: "text_delta" })).toBeNull();
    expect(decode({ type: "iteration", message: "无 round" })).toBeNull();
    expect(normalizeEvent({})).toBeNull();
  });
});
