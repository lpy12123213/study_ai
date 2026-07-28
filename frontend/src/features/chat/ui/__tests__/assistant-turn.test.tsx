import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeChatEvent } from "../../streaming/contract";
import { chatProjectionReducer, initialChatProjection, type ChatProjectionState } from "../../model/reducer";
import type { ThinkingBlockView } from "../../model/types";
import {
  createPaperStream,
  interruptedPrefixStream,
  parallelToolsStream,
  thinkingSerialToolsStream,
  type ChatWireEvent,
} from "../../streaming/__fixtures__/chat-streams";
import { AssistantTurn } from "../assistant-turn";
import { formatObservedDuration } from "../format";
import { IterationTimeline } from "../iteration-timeline";
import { ThinkingText } from "../thinking-text";

function project(events: ChatWireEvent[]): ChatProjectionState {
  let state = initialChatProjection();
  let at = 1_000;
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

const thinkingView = (over: Partial<ThinkingBlockView> = {}): ThinkingBlockView => ({
  text: "先分析题目条件，\n再列出可能的解法，\n然后逐步验证，\n最后给出结论。\n补充一行细节。",
  status: "done",
  durationMs: 2500,
  userVisible: true,
  ...over,
});

describe("ThinkingText", () => {
  it("流式中显示「思考中…」，完成后显示客户端观察耗时", () => {
    const { rerender } = render(<ThinkingText thinking={thinkingView({ status: "streaming", durationMs: undefined })} />);
    expect(screen.getByText("思考中…")).toBeInTheDocument();
    rerender(<ThinkingText thinking={thinkingView()} />);
    expect(screen.getByText("思考完成 · 2.5 秒")).toBeInTheDocument();
  });

  it("默认限制约 4 行，可展开全部与收起", () => {
    const { container } = render(<ThinkingText thinking={thinkingView()} />);
    expect(container.querySelector(".line-clamp-4")).not.toBeNull();
    fireEvent.click(screen.getByText("展开全部"));
    expect(container.querySelector(".line-clamp-4")).toBeNull();
    fireEvent.click(screen.getByText("收起"));
    expect(container.querySelector(".line-clamp-4")).not.toBeNull();
  });

  it("历史轮可整体折叠为 pill 摘要", () => {
    const { container } = render(<ThinkingText thinking={thinkingView()} defaultExpanded={false} />);
    const pill = screen.getByRole("button", { name: /思考完成 · 2.5 秒/ });
    expect(pill).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector("[aria-label='思考过程']")).toBeNull();
    fireEvent.click(pill);
    expect(container.querySelector("[aria-label='思考过程']")).not.toBeNull();
  });

  it("观察耗时格式化", () => {
    expect(formatObservedDuration(800)).toBe("0.8 秒");
    expect(formatObservedDuration(2500)).toBe("2.5 秒");
    expect(formatObservedDuration(12000)).toBe("12 秒");
  });
});

describe("IterationTimeline", () => {
  it("多轮时间线：已完成 iteration 默认折叠，当前 iteration 默认展开", () => {
    const state = project(thinkingSerialToolsStream);
    render(<IterationTimeline turn={state.turn} />);

    // 第 1 轮已折叠：意图不可见，但有一行摘要
    expect(screen.queryByText("关键词「数列综合」")).not.toBeInTheDocument();
    expect(screen.getByText(/题库搜索（1 个工具/)).toBeInTheDocument();

    // 第 2 轮（最新）展开：意图与结果摘要可见
    expect(screen.getByText("搜索「高考数学 数列综合题 真题」")).toBeInTheDocument();
    expect(screen.getByText(/返回 2 个来源/)).toBeInTheDocument();

    // 展开第 1 轮
    fireEvent.click(screen.getByRole("button", { name: /第 1 轮/ }));
    expect(screen.getByText("关键词「数列综合」")).toBeInTheDocument();
    expect(screen.getByText(/找到 2 道候选题/)).toBeInTheDocument();
  });

  it("同轮多工具并列展示且带状态图标与文字", () => {
    const state = project(parallelToolsStream);
    render(<IterationTimeline turn={state.turn} />);
    expect(screen.getByText("题库搜索")).toBeInTheDocument();
    expect(screen.getByText("网络搜索")).toBeInTheDocument();
    expect(screen.getAllByText("已完成").length).toBeGreaterThanOrEqual(2);
  });

  it("单工具自动收缩为行内执行组（无轮次标题）", () => {
    const state = project(createPaperStream);
    render(<IterationTimeline turn={state.turn} />);
    expect(screen.queryByRole("button", { name: /第 1 轮/ })).not.toBeInTheDocument();
    expect(screen.getByText("创建试卷")).toBeInTheDocument();
    expect(screen.getByText(/试卷已创建（ID: 208）/)).toBeInTheDocument();
  });
});

describe("AssistantTurn", () => {
  it("按层级渲染：思考 → 时间线 → 最终答案", () => {
    const state = project(thinkingSerialToolsStream);
    const { container } = render(
      <AssistantTurn turn={state.turn} current>
        <div data-testid="answer">{state.turn.finalText}</div>
      </AssistantTurn>,
    );
    expect(screen.getByText("思考完成 · 1.7 秒")).toBeInTheDocument();
    expect(screen.getByTestId("answer")).toHaveTextContent("下面是一道数列综合练习题");
    // 思考在时间线之前，时间线在答案之前
    const order = container.innerHTML;
    expect(order.indexOf("思考过程")).toBeLessThan(order.indexOf("工具执行时间线"));
    expect(order.indexOf("工具执行时间线")).toBeLessThan(order.indexOf('data-testid="answer"'));
  });

  it("interrupted：显示停止接收提示，不伪装完成", () => {
    let state = project(interruptedPrefixStream);
    state = chatProjectionReducer(state, { type: "settled", reason: "aborted", at: 50_000 });
    render(<AssistantTurn turn={state.turn} current />);
    expect(screen.getByText(/已停止接收，以上内容可能不完整/)).toBeInTheDocument();
    expect(screen.queryByText("已完成")).not.toBeInTheDocument();
  });

  it("error：显示失败图标与可读原因", () => {
    const state = project([
      { type: "stream_start", iteration: 1 },
      { type: "error", content: "api_error" },
    ]);
    render(<AssistantTurn turn={state.turn} current />);
    expect(screen.getByRole("alert")).toHaveTextContent("失败：api_error");
  });

  it("空流式状态显示轻量「正在思考…」", () => {
    const state = project([{ type: "stream_start", iteration: 1 }]);
    render(<AssistantTurn turn={state.turn} current />);
    expect(screen.getByText("正在思考…")).toBeInTheDocument();
  });
});
