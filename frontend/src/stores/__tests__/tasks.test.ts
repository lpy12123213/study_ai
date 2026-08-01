import { beforeEach, describe, expect, it } from "vitest";

import type { TaskEvent } from "@/shared/api/types";
import { useTasksStore } from "../tasks";

function ev(type: string, data: Record<string, unknown>, seq: number, taskId = "t-1"): TaskEvent {
  return { type, data, seq, taskId };
}

describe("tasks store：subagents 记录", () => {
  beforeEach(() => {
    useTasksStore.setState({ active: {} });
  });

  it("并行子代理按 subagent_id 分组，steps 归属不串，状态 running→done 流转", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    const events: TaskEvent[] = [
      ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 3, kind: "knowledge_research" }, 1),
      ev("subagent_start", { knowledge_point: "暗反应", subagent_id: "sa-2", index: 2, total: 3, kind: "knowledge_research" }, 2),
      ev("tool_call", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1", knowledge_point: "光反应" }, 3),
      ev("tool_call", { step_id: "sa2-web-1", name: "web_search_knowledge", subagent_id: "sa-2", knowledge_point: "暗反应" }, 4),
      ev("tool_result", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1", success: true, elapsed_ms: 1200 }, 5),
      ev("tool_result", { step_id: "sa2-web-1", name: "web_search_knowledge", subagent_id: "sa-2", success: true, elapsed_ms: 900 }, 6),
      ev("subagent_end", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 3 }, 7),
      ev("subagent_end", { knowledge_point: "暗反应", subagent_id: "sa-2", index: 2, total: 3 }, 8),
    ];
    for (const event of events) store.applyEvent("t-1", event);

    const subagents = useTasksStore.getState().active["t-1"].subagents ?? {};
    expect(Object.keys(subagents).sort()).toEqual(["sa-1", "sa-2"]);
    const sa1 = subagents["sa-1"];
    expect(sa1).toMatchObject({
      kp: "光反应",
      kind: "knowledge_research",
      index: 1,
      total: 3,
      status: "done",
    });
    expect(sa1.steps).toHaveLength(1);
    expect(sa1.steps[0]).toMatchObject({
      stepId: "sa1-web-1",
      status: "success",
      success: true,
      elapsedMs: 1200,
    });
    const sa2 = subagents["sa-2"];
    expect(sa2.steps[0]).toMatchObject({ stepId: "sa2-web-1", status: "success" });
    // 无跨子代理泄漏。
    expect(sa1.steps.map((step) => step.stepId)).toEqual(["sa1-web-1"]);
    expect(sa2.steps.map((step) => step.stepId)).toEqual(["sa2-web-1"]);
  });

  it("失败 tool_result 把步骤标记 error 并保留错误文案", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 1 }, 1));
    store.applyEvent("t-1", ev("tool_call", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1" }, 2));
    store.applyEvent("t-1", ev("tool_result", { step_id: "sa1-web-1", subagent_id: "sa-1", success: false, error: "llm_request_failed" }, 3));
    const step = useTasksStore.getState().active["t-1"].subagents?.["sa-1"].steps[0];
    expect(step).toMatchObject({ status: "error", success: false, summary: "llm_request_failed" });
  });

  it("legacy 事件（无子代理标字段）保持 subagents 为空", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    const events: TaskEvent[] = [
      ev("task_started", { taskId: "t-1" }, 1),
      ev("status", { content: "规划中" }, 2),
      ev("tool_call", { step_id: "m-1", name: "split_knowledge_points", arguments: { topic: "函数单调性" } }, 3),
      ev("tool_result", { step_id: "m-1", name: "split_knowledge_points", success: true }, 4),
      ev("done", { success: true }, 5),
    ];
    for (const event of events) store.applyEvent("t-1", event);
    expect(useTasksStore.getState().active["t-1"].subagents).toEqual({});
  });

  it("无 subagent_id 的 subagent_start/end 不建 record（旧事件降级为现状）", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    const events: TaskEvent[] = [
      ev("subagent_start", { knowledge_point: "光反应" }, 1),
      ev("subagent_end", { knowledge_point: "光反应" }, 2),
    ];
    for (const event of events) store.applyEvent("t-1", event);
    expect(useTasksStore.getState().active["t-1"].subagents).toEqual({});
  });

  it("lesson_plan 形状事件（kp + index/total、无 subagent_id）不建 record", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    const events: TaskEvent[] = [
      ev("subagent_start", { knowledge_point: "函数单调性", index: 0, total: 2, content: "SubAgent 启动：研究知识点「函数单调性」" }, 1),
      ev("subagent_start", { knowledge_point: "导数应用", index: 1, total: 2, content: "SubAgent 启动：研究知识点「导数应用」" }, 2),
      ev("subagent_end", { knowledge_point: "函数单调性", index: 0, total: 2 }, 3),
      ev("subagent_end", { knowledge_point: "导数应用", index: 1, total: 2 }, 4),
    ];
    for (const event of events) store.applyEvent("t-1", event);
    expect(useTasksStore.getState().active["t-1"].subagents).toEqual({});
  });

  it("seq 去重：重复 applyEvent 不会重复追加步骤", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 3 }, 1));
    store.applyEvent("t-1", ev("tool_call", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1" }, 2));
    // 重复投递同一批事件（回放幂等路径）。
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 3 }, 1));
    store.applyEvent("t-1", ev("tool_call", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1" }, 2));
    const subagents = useTasksStore.getState().active["t-1"].subagents ?? {};
    expect(subagents["sa-1"].steps).toHaveLength(1);
  });

  it("tool_call 先于 subagent_start 到达（未知 id）：静默丢弃，不建 record、不报错", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    store.applyEvent("t-1", ev("tool_call", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1" }, 1));
    expect(useTasksStore.getState().active["t-1"].subagents).toEqual({});
    // 后续 start 正常建 record；早到的 tool_call 不回溯补录。
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 1 }, 2));
    const record = useTasksStore.getState().active["t-1"].subagents?.["sa-1"];
    expect(record?.status).toBe("running");
    expect(record?.steps).toEqual([]);
  });

  it("tool_call/tool_result 带未知 subagent_id：静默丢弃，不建 record、不报错", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 1 }, 1));
    store.applyEvent("t-1", ev("tool_call", { step_id: "ghost-1", name: "web_search_knowledge", subagent_id: "sa-ghost" }, 2));
    store.applyEvent("t-1", ev("tool_result", { step_id: "ghost-1", subagent_id: "sa-ghost", success: true }, 3));
    const subagents = useTasksStore.getState().active["t-1"].subagents ?? {};
    expect(Object.keys(subagents)).toEqual(["sa-1"]);
    expect(subagents["sa-1"].steps).toEqual([]);
  });

  it("subagent_end 后迟到的 tool_result：record 仍在，能修补对应 step 状态", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 1 }, 1));
    store.applyEvent("t-1", ev("tool_call", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1" }, 2));
    store.applyEvent("t-1", ev("subagent_end", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 1 }, 3));
    // end 之后迟到的结果：record 保留 done，step 状态仍可修补。
    store.applyEvent("t-1", ev("tool_result", { step_id: "sa1-web-1", subagent_id: "sa-1", success: true, elapsed_ms: 800 }, 4));
    const record = useTasksStore.getState().active["t-1"].subagents?.["sa-1"];
    expect(record?.status).toBe("done");
    expect(record?.steps[0]).toMatchObject({ stepId: "sa1-web-1", status: "success", elapsedMs: 800 });
  });

  it("同一 subagent_id 再次 subagent_start：steps 重置、status 归 running（契约锁定）", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 3, kind: "knowledge_research" }, 1));
    store.applyEvent("t-1", ev("tool_call", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1" }, 2));
    store.applyEvent("t-1", ev("subagent_end", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 3 }, 3));
    // 重规划复用同一 subagent_id：新一轮重置，kp/index/total 用新事件值。
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应（重试）", subagent_id: "sa-1", index: 1, total: 4, kind: "knowledge_research" }, 4));
    const record = useTasksStore.getState().active["t-1"].subagents?.["sa-1"];
    expect(record).toMatchObject({ kp: "光反应（重试）", index: 1, total: 4, status: "running" });
    expect(record?.steps).toEqual([]);
  });

  it("tool_call/tool_result 不可变替换 record：引用变化且不污染旧快照", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 1 }, 1));
    const before = useTasksStore.getState().active["t-1"].subagents?.["sa-1"];
    store.applyEvent("t-1", ev("tool_call", { step_id: "sa1-web-1", name: "web_search_knowledge", subagent_id: "sa-1" }, 2));
    const afterCall = useTasksStore.getState().active["t-1"].subagents?.["sa-1"];
    store.applyEvent("t-1", ev("tool_result", { step_id: "sa1-web-1", subagent_id: "sa-1", success: true }, 3));
    const afterResult = useTasksStore.getState().active["t-1"].subagents?.["sa-1"];
    expect(afterCall).not.toBe(before);
    expect(afterResult).not.toBe(afterCall);
    // 原地修改会击穿这两条断言：旧快照被后续事件污染。
    expect(before?.steps).toEqual([]);
    expect(afterCall?.steps[0]?.status).toBe("running");
  });

  it("steps 超过 50 上限：丢弃最旧、保留最新", () => {
    const store = useTasksStore.getState();
    store.register("t-1");
    store.applyEvent("t-1", ev("subagent_start", { knowledge_point: "光反应", subagent_id: "sa-1", index: 1, total: 1 }, 1));
    for (let i = 1; i <= 55; i += 1) {
      store.applyEvent("t-1", ev("tool_call", { step_id: `sa1-t-${i}`, name: "web_search_knowledge", subagent_id: "sa-1" }, 1 + i));
    }
    const steps = useTasksStore.getState().active["t-1"].subagents?.["sa-1"].steps ?? [];
    expect(steps).toHaveLength(50);
    expect(steps[0]?.stepId).toBe("sa1-t-6");
    expect(steps[49]?.stepId).toBe("sa1-t-55");
  });
});
