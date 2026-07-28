import { describe, expect, it } from "vitest";

import { normalizeEvent, SseParser } from "@/lib/sse";

/**
 * Characterization tests：固定当前 SseParser / normalizeEvent 行为。
 * 后续 transport 重构（架构 Phase 3）必须以这些行为为基线。
 */

describe("SseParser", () => {
  it("解析单个完整帧", () => {
    const p = new SseParser();
    expect(p.push('data: {"type":"ping"}\n\n')).toEqual(['{"type":"ping"}']);
  });

  it("跨 push 拼接收到的分块帧", () => {
    const p = new SseParser();
    expect(p.push('data: {"type":"text_d')).toEqual([]);
    expect(p.push('elta","content":"a"}\n\n')).toEqual(['{"type":"text_delta","content":"a"}']);
  });

  it("一次 push 中的多个帧按序返回", () => {
    const p = new SseParser();
    const frames = p.push("data: a\n\ndata: b\n\ndata: c\n\n");
    expect(frames).toEqual(["a", "b", "c"]);
  });

  it("兼容 \\r\\n 分隔", () => {
    const p = new SseParser();
    expect(p.push("data: a\r\n\r\n")).toEqual(["a"]);
  });

  it("合并多行 data 并以 \\n 连接", () => {
    const p = new SseParser();
    expect(p.push("data: line1\ndata: line2\n\n")).toEqual(["line1\nline2"]);
  });

  it("忽略注释行与非 data 字段行", () => {
    const p = new SseParser();
    expect(p.push(": ping\nevent: message\ndata: x\n\n")).toEqual(["x"]);
  });

  it("剥离 data: 后的单个前导空格", () => {
    const p = new SseParser();
    expect(p.push("data:  spaced\n\n")).toEqual([" spaced"]);
  });

  it("末尾不完整帧保留在缓冲区", () => {
    const p = new SseParser();
    expect(p.push("data: done\n\ndata: partial")).toEqual(["done"]);
    expect(p.push("-frame\n\n")).toEqual(["partial-frame"]);
  });

  it("空 data 载荷不产生帧", () => {
    const p = new SseParser();
    expect(p.push("data:\n\ndata:   \n\n")).toEqual([]);
  });
});

describe("normalizeEvent", () => {
  it("扁平事件：extra 字段进入 data，seq 默认为 0", () => {
    const ev = normalizeEvent({ type: "text_delta", content: "你好", iteration: 2 });
    expect(ev).not.toBeNull();
    expect(ev?.type).toBe("text_delta");
    expect(ev?.data).toEqual({ content: "你好", iteration: 2 });
    expect(ev?.seq).toBe(0);
    expect(ev?.taskId).toBeUndefined();
  });

  it("任务信封：data 对象展开并与 extra 合并，保留 seq/taskId", () => {
    const ev = normalizeEvent({
      taskId: "t-1",
      seq: 42,
      type: "progress",
      created_at: "2026-07-26T00:00:00Z",
      data: { percent: 30 },
      stage: "generate",
    });
    expect(ev?.seq).toBe(42);
    expect(ev?.taskId).toBe("t-1");
    expect(ev?.data).toEqual({ percent: 30, stage: "generate" });
    // 保留字不进入 data
    expect(ev?.data).not.toHaveProperty("created_at");
    expect(ev?.raw).toMatchObject({ seq: 42 });
  });

  it("非对象 data 包装为 { value }", () => {
    expect(normalizeEvent({ type: "x", data: "raw-text" })?.data).toEqual({ value: "raw-text" });
    expect(normalizeEvent({ type: "x", data: [1, 2] })?.data).toEqual({ value: [1, 2] });
  });

  it("extra 与 data 内字段同名时 extra 优先", () => {
    const ev = normalizeEvent({ type: "x", data: { k: "inner" }, k: "outer" });
    expect(ev?.data).toEqual({ k: "outer" });
  });

  it("非对象或缺少 type 返回 null", () => {
    expect(normalizeEvent(null)).toBeNull();
    expect(normalizeEvent("text")).toBeNull();
    expect(normalizeEvent({})).toBeNull();
    expect(normalizeEvent({ type: 1 })).toBeNull();
    expect(normalizeEvent({ type: "" })).toBeNull();
  });
});
