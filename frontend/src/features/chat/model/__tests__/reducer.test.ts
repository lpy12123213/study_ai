import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeChatEvent } from "../../streaming/contract";
import {
  chatProjectionReducer,
  initialChatProjection,
  type ChatProjectionState,
  type StreamEndReason,
} from "../reducer";
import { selectCompactTool, selectTimelineSummary, selectVisibleIterations, selectVisibleText } from "../selectors";
import {
  computeAndPlotStream,
  createPaperStream,
  interruptedPrefixStream,
  maxIterationsStream,
  parallelToolsStream,
  simpleTextStream,
  terminalErrorStream,
  thinkingSerialToolsStream,
  toolFailureStream,
  type ChatWireEvent,
} from "../../streaming/__fixtures__/chat-streams";

/** 把 wire 事件序列经 normalize → decode → reduce 投影，事件间隔 100ms 观察时间。 */
function project(events: ChatWireEvent[], startAt = 1_000): ChatProjectionState {
  let state = initialChatProjection();
  let at = startAt;
  for (const raw of events) {
    const normalized = normalizeEvent(raw);
    if (!normalized) continue;
    const decoded = decodeChatEvent(normalized);
    if (!decoded) continue;
    state = chatProjectionReducer(state, { type: "event", event: decoded, at });
    at += 100;
  }
  return state;
}

function settle(state: ChatProjectionState, reason: StreamEndReason, at = 100_000, error?: Error): ChatProjectionState {
  return chatProjectionReducer(state, { type: "settled", reason, at, ...(error ? { error } : {}) });
}

describe("chat projection：文本与思考", () => {
  it("纯文本流：text_delta 追加，assistant_final 落入 finalText", () => {
    const state = settle(project(simpleTextStream), "completed");
    expect(state.turn.runStatus).toBe("done");
    expect(selectVisibleText(state.turn)).toBe("二次函数顶点式 $y=a(x-h)^2+k$ 的顶点坐标是 $(h,k)$。");
    expect(state.turn.thinking).toBeUndefined();
    expect(selectVisibleIterations(state.turn)).toHaveLength(0);
  });

  it("thinking_delta 顺序追加，final 后标记 done 并给出客户端观察耗时", () => {
    const state = settle(project(thinkingSerialToolsStream), "completed");
    const thinking = state.turn.thinking;
    expect(thinking).toBeDefined();
    expect(thinking?.text).toContain("用户想找数列综合练习题。");
    expect(thinking?.text).toContain("信息足够，整理练习题与解析。");
    expect(thinking?.status).toBe("done");
    expect(thinking?.durationMs).toBeGreaterThan(0);
    expect(thinking?.userVisible).toBe(true);
  });

  it("决策轮文本与最终答案分别投影：最终正文不含轮次中间消息", () => {
    const state = project(thinkingSerialToolsStream);
    expect(state.turn.finalText).toContain("下面是一道数列综合练习题");
    expect(state.turn.finalText).not.toContain("好的，我先在题库中搜索");
    expect(state.turn.finalText).not.toContain("已找到 2 道候选题");
  });

  it("remaining 场景：无 phase 的 text_delta 接在同轮决策文本后", () => {
    const state = project([
      { type: "stream_start", iteration: 1, phase: "tool_decision" },
      { type: "text_delta", content: "答案是 ", iteration: 1, phase: "tool_decision" },
      { type: "text_delta", content: "42。" },
      { type: "assistant_final", content: "答案是 42。", total_iterations: 1 },
    ]);
    expect(state.turn.finalText).toBe("答案是 42。");
  });

  it("assistant_final content 为空时回退到已流式文本", () => {
    const state = project([
      { type: "stream_start", iteration: 1 },
      { type: "text_delta", content: "部分内容" },
      { type: "assistant_final", content: "", total_iterations: 1 },
    ]);
    expect(state.turn.finalText).toBe("部分内容");
  });
});

describe("chat projection：工具时间线", () => {
  it("tool_start 保存 arguments 与 iteration；tool_result 按 call ID 合并", () => {
    const state = settle(project(thinkingSerialToolsStream), "completed");
    const iterations = selectVisibleIterations(state.turn);
    expect(iterations).toHaveLength(2);

    const [first, second] = iterations;
    expect(first.index).toBe(1);
    expect(first.tools).toHaveLength(1);
    expect(first.tools[0]).toMatchObject({
      id: "call_9f3k2",
      name: "search_questions",
      displayName: "题库搜索",
      status: "success",
      iteration: 1,
      summary: "找到 2 道候选题",
    });
    expect(first.tools[0].arguments).toMatchObject({ keyword: "数列综合" });
    expect(first.tools[0].observedStartAt).toBeDefined();
    expect(first.tools[0].observedResultAt).toBeDefined();

    expect(second.index).toBe(2);
    expect(second.tools[0]).toMatchObject({ name: "web_search", status: "success", summary: "返回 2 个来源" });
    expect(state.turn.runStatus).toBe("done");
  });

  it("同一 iteration 的多工具保持同轮分组（不伪造并行/串行关系）", () => {
    const state = settle(project(parallelToolsStream), "completed");
    const iterations = selectVisibleIterations(state.turn);
    expect(iterations).toHaveLength(1);
    expect(iterations[0].tools.map((t) => t.name)).toEqual(["search_questions", "web_search"]);
    expect(iterations[0].tools.every((t) => t.status === "success")).toBe(true);
    expect(iterations[0].status).toBe("success");
    // 不展示单工具权威耗时：仅有观察时间戳
    expect(iterations[0].tools[0].serverDurationMs).toBeUndefined();
  });

  it("工具失败不终止轮次投影：iteration 标记 error，turn 仍可完成", () => {
    const state = settle(project(toolFailureStream), "completed");
    const iterations = selectVisibleIterations(state.turn);
    expect(iterations[0].tools[0]).toMatchObject({ status: "error", summary: "题库登录态失效" });
    expect(iterations[0].status).toBe("error");
    expect(state.turn.runStatus).toBe("done");
    expect(selectVisibleText(state.turn)).toContain("题库当前不可用");
  });

  it("媒体与计算工具保存结果并生成摘要", () => {
    const state = settle(project(computeAndPlotStream), "completed");
    const tools = selectVisibleIterations(state.turn)[0].tools;
    expect(tools[0]).toMatchObject({ name: "python_scientific_compute", summary: "结果：[2, 3]" });
    expect(tools[1]).toMatchObject({ name: "plot_function", summary: "已生成图像" });
    expect(tools[1].result).toMatchObject({ url: "/api/media/generated/plot-abc123.png" });
  });

  it("create_paper 结果摘要包含试卷 ID", () => {
    const state = settle(project(createPaperStream), "completed");
    const tool = selectVisibleIterations(state.turn)[0].tools[0];
    expect(tool).toMatchObject({ displayName: "创建试卷", status: "success", summary: "试卷已创建（ID: 208）" });
  });

  it("达到最大轮数时 maxReached 为真", () => {
    const state = settle(project(maxIterationsStream), "completed");
    expect(state.turn.runStatus).toBe("done");
    expect(state.turn.maxReached).toBe(true);
    expect(state.turn.finalText).toContain("已完成 5 轮操作。");
  });

  it("单工具轮次进入紧凑态候选，多工具不进入", () => {
    const single = settle(project(createPaperStream), "completed");
    expect(selectCompactTool(single.turn)?.name).toBe("create_paper");
    const multi = settle(project(parallelToolsStream), "completed");
    expect(selectCompactTool(multi.turn)).toBeNull();
  });

  it("时间线聚合成一行可读摘要", () => {
    const state = settle(project(parallelToolsStream), "completed");
    expect(selectTimelineSummary(state.turn)).toBe("工具执行完成：共 2 个");
  });
});

describe("chat projection：终止语义", () => {
  it("终态 error 事件：turn 进入 error，活动工具标记 error", () => {
    const state = settle(project(terminalErrorStream), "completed");
    expect(state.turn.runStatus).toBe("error");
    expect(state.turn.errorMessage).toBe("api_error");
    expect(state.turn.finalText).toBe("");
  });

  it("Abort：保留已收到的思考与部分正文，turn 标记 interrupted", () => {
    let state = project(interruptedPrefixStream);
    state = chatProjectionReducer(state, { type: "stop_requested", at: 50_000 });
    state = settle(state, "aborted");
    expect(state.stopIntent).toBe(true);
    expect(state.turn.runStatus).toBe("interrupted");
    expect(state.turn.thinking?.text).toBe("先在题库中搜索…");
    expect(state.turn.thinking?.status).toBe("done");
    const tool = selectVisibleIterations(state.turn)[0].tools[0];
    expect(tool.status).toBe("interrupted");
    // 中断不是完成：不产生 finalText
    expect(state.turn.finalText).toBe("");
  });

  it("无 final 的 [DONE]（completed）不被误判为成功", () => {
    const state = settle(project(interruptedPrefixStream), "completed");
    expect(state.turn.runStatus).toBe("interrupted");
  });

  it("无 final 的普通 EOF 不被误判为成功", () => {
    const state = settle(project(interruptedPrefixStream), "eof");
    expect(state.turn.runStatus).toBe("interrupted");
  });

  it("transport error（无 error 事件）：turn error，活动工具标记 interrupted（状态未知）", () => {
    const state = settle(project(interruptedPrefixStream), "error", 100_000, new Error("network down"));
    expect(state.turn.runStatus).toBe("error");
    expect(state.turn.errorMessage).toBe("network down");
    expect(selectVisibleIterations(state.turn)[0].tools[0].status).toBe("interrupted");
  });

  it("final 之后再收到 settled 只记录 termination，不改变投影", () => {
    let state = project(simpleTextStream);
    state = settle(state, "aborted");
    expect(state.turn.runStatus).toBe("done");
    expect(state.termination).toBe("aborted");
  });

  it("终态后到达的事件被忽略", () => {
    let state = project(simpleTextStream);
    const before = state.turn;
    state = chatProjectionReducer(state, {
      type: "event",
      event: { kind: "text_delta", content: "残留帧" },
      at: 200_000,
    });
    expect(state.turn).toBe(before);
  });
});
