import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { TaskEvent } from "@/shared/api/types";
import { useTasksStore } from "@/stores/tasks";
import { SubAgentPanel } from "../sub-agent-panel";

function ev(type: string, data: Record<string, unknown>, seq: number): TaskEvent {
  return { type, data, seq, taskId: "t-1" };
}

function seedTwoParallelSubAgents() {
  const store = useTasksStore.getState();
  store.register("t-1");
  const events: TaskEvent[] = [
    ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 3, kind: "knowledge_research" }, 1),
    ev("subagent_start", { knowledge_point: "暗反应", subagent_id: "sa-2", index: 2, total: 3, kind: "knowledge_research" }, 2),
    ev("tool_call", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1" }, 3),
    ev("tool_result", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1", success: true, elapsed_ms: 1200 }, 4),
    ev("subagent_end", { knowledge_point: "光反应", subagent_id: "sa-1" }, 5),
    ev("subagent_end", { knowledge_point: "暗反应", subagent_id: "sa-2" }, 6),
  ];
  for (const event of events) store.applyEvent("t-1", event);
}

describe("SubAgentPanel", () => {
  beforeEach(() => {
    useTasksStore.setState({ active: {} });
  });

  it("无子代理记录时渲染 null", () => {
    const { container } = render(<SubAgentPanel taskId="t-1" />);
    expect(container.firstChild).toBeNull();
  });

  it("无 subagent_id 的 subagent 事件（含 lesson_plan 形状）不渲染面板", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", index: 0, total: 2 }, 1));
    store.applyEvent("t-1", ev("subagent_end", { knowledge_point: "光反应", index: 0, total: 2 }, 2));
    const { container } = render(<SubAgentPanel taskId="t-1" />);
    expect(container.firstChild).toBeNull();
  });

  it("并行 2 个子代理卡片渲染，折叠标题含 kp + index/total，展开显示嵌套步骤", () => {
    seedTwoParallelSubAgents();
    render(<SubAgentPanel taskId="t-1" />);
    expect(screen.getByText("光反应 · 1/3")).toBeInTheDocument();
    expect(screen.getByText("暗反应 · 2/3")).toBeInTheDocument();
    expect(screen.getAllByText("已完成").length).toBeGreaterThanOrEqual(2);
    // 步骤默认折叠。
    expect(screen.queryByText("web_search_knowledge")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /光反应/ }));
    expect(screen.getByText("web_search_knowledge")).toBeInTheDocument();
  });
});
