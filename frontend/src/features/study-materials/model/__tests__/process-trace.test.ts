import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import type { StudyTaskTracePage } from "../../api";
import { decodeStudyMaterialsEvent } from "../../streaming/contract";
import { sectionStatusText } from "../../ui/section-status-text";
import {
  initialStudyMaterialsProjection,
  studyMaterialsProjectionReducer,
} from "../reducer";
import {
  legacyStudyMaterialsStream,
  traceAgentStream,
  type StudyMaterialsWireEvent,
} from "../../streaming/__fixtures__/study-materials-streams";

/** 新版过程事件流：agent_path 泳道 + todos + 思考/笔记/配图/填充。 */
const traceStream = traceAgentStream;

function decode(raw: Record<string, unknown>) {
  const normalized = normalizeEvent(raw);
  if (!normalized) throw new Error("fixture did not normalize");
  return decodeStudyMaterialsEvent(normalized);
}

function project(events: StudyMaterialsWireEvent[]) {
  return events.reduce((state, raw, index) => {
    const normalized = normalizeEvent(raw);
    if (!normalized) return state;
    const event = decodeStudyMaterialsEvent(normalized);
    if (!event) return state;
    return studyMaterialsProjectionReducer(state, {
      type: "event",
      event,
      seq: normalized.seq,
      at: 1_000 + index * 100,
    });
  }, initialStudyMaterialsProjection());
}

describe("study-materials trace contract", () => {
  it("thinking_delta 解码 data.text 与 agentPath", () => {
    expect(decode(traceStream[3])).toEqual({
      kind: "thinking_delta",
      text: "先列大纲。",
      agentPath: "main",
    });
    expect(decode(traceStream[4])).toMatchObject({
      kind: "thinking_delta",
      text: "组织本节材料。",
      agentPath: "fill:sec-1",
    });
  });

  it("note_write / figure_trace / section_fill 解码 agentPath", () => {
    expect(decode(traceStream[5])).toEqual({
      kind: "note_write",
      name: "sec-1-photosynthesis",
      chars: 120,
      agentPath: "fill:sec-1",
    });
    expect(decode(traceStream[7])).toEqual({
      kind: "figure_trace",
      figureId: "1",
      stage: "render_ok",
      engine: "mermaid",
      url: "/api/media/generated/fig-1.svg",
      agentPath: "fig:1",
    });
    // section_fill 状态词表为 start|ok|retry|failed（author/fill.py）。
    expect(decode(traceStream[8])).toEqual({
      kind: "section_fill",
      secId: "sec-1",
      status: "ok",
      agentPath: "fill:sec-1",
    });
  });

  it("todo_update 解码完整 todo；缺省 agent_path 降级为 main", () => {
    expect(decode(traceStream[1])).toEqual({
      kind: "todo_update",
      todo: {
        id: "t1",
        type: "research",
        ref: "光反应",
        status: "in_progress",
        acceptance: "覆盖 3 个来源",
      },
      agentPath: "main",
    });
    expect(
      decode({
        taskId: "materials-trace-1",
        seq: 99,
        type: "section_fill",
        data: { sec_id: "sec-9", status: "started" },
      }),
    ).toMatchObject({ kind: "section_fill", agentPath: "main" });
  });

  it("todo_update 缺少 todo.id 时不解码", () => {
    expect(
      decode({ taskId: "materials-trace-1", seq: 98, type: "todo_update", data: { todo: {} } }),
    ).toBeNull();
  });

  it("tool_call 透传 agentPath；旧事件不带则不注入", () => {
    expect(decode(traceStream[6])).toMatchObject({
      kind: "tool_call",
      stepId: "fill-sec-1-write",
      agentPath: "fill:sec-1",
    });
    expect(decode(legacyStudyMaterialsStream[3])).not.toHaveProperty("agentPath");
  });

  it("legacy thinking / reasoning_delta 保持旧解码形状", () => {
    expect(decode(legacyStudyMaterialsStream[2])).toEqual({
      kind: "thinking",
      content: "先拆分定义、判定方法与典型误区。",
    });
  });
});

describe("study-materials process reducer", () => {
  it("todo_update 更新 todos map：同 id 覆盖，键序保持首次出现顺序", () => {
    const state = project(traceStream);
    expect(Object.keys(state.todos)).toEqual(["t1", "t2"]);
    expect(state.todos.t1).toMatchObject({
      type: "research",
      status: "done",
      note: "3 个来源已覆盖",
    });
    expect(state.todos.t2).toMatchObject({ type: "fill", ref: "sec-1", status: "pending" });
  });

  it("traceByAgent 按 agentPath 分泳道，fill/fig 独立于 main", () => {
    const state = project(traceStream);
    expect(Object.keys(state.traceByAgent).sort()).toEqual(["fig:1", "fill:sec-1", "main"]);
    // main 泳道：两条相邻 thinking_delta 合并为一个思考块。
    expect(state.traceByAgent.main).toHaveLength(1);
    expect(state.traceByAgent.main[0]).toMatchObject({
      kind: "thinking",
      text: "先列大纲。继续填充下一节。",
    });
    expect(state.traceByAgent["fill:sec-1"].map((entry) => entry.kind)).toEqual([
      "thinking",
      "note",
      "tool",
      "section",
    ]);
    expect(state.traceByAgent["fig:1"]).toEqual([
      expect.objectContaining({ kind: "figure", figureId: "1", stage: "render_ok" }),
    ]);
  });

  it("section_fill 更新每节状态", () => {
    const state = project(traceStream);
    expect(state.sectionStatus).toEqual({ "sec-1": "ok" });
  });

  it("legacy 流不产生 todos/trace 切片（旧任务回放不回归）", () => {
    const state = project(legacyStudyMaterialsStream);
    expect(state.todos).toEqual({});
    expect(state.traceByAgent).toEqual({});
    expect(state.sectionStatus).toEqual({});
  });
});

describe("study-materials 后端真实事件形状（C-1/I-3/M-1）", () => {
  it("figure_trace 接受数字 figure_id，并按 stage 词表透传 engine/url/error", () => {
    // codegen 阶段：仅 figure_id + stage（chars 等额外字段忽略）。
    expect(
      decode({
        taskId: "materials-trace-1",
        seq: 20,
        type: "figure_trace",
        agent_path: "fig:2",
        data: { figure_id: 2, stage: "codegen", chars: 512 },
      }),
    ).toEqual({ kind: "figure_trace", figureId: "2", stage: "codegen", agentPath: "fig:2" });
    // render_fail 阶段：engine + error 透传，整条事件不丢弃。
    expect(
      decode({
        taskId: "materials-trace-1",
        seq: 21,
        type: "figure_trace",
        agent_path: "fig:2",
        data: { figure_id: 2, stage: "render_fail", engine: "tikz", error: "tikz_render_failed" },
      }),
    ).toEqual({
      kind: "figure_trace",
      figureId: "2",
      stage: "render_fail",
      engine: "tikz",
      error: "tikz_render_failed",
      agentPath: "fig:2",
    });
  });

  it("figure_trace 缺 figure_id 时不解码", () => {
    expect(
      decode({
        taskId: "materials-trace-1",
        seq: 22,
        type: "figure_trace",
        data: { stage: "codegen" },
      }),
    ).toBeNull();
  });

  it("author 流水线 tool_call 形状（tool/query/result_count/stage/sec_id/error）可容忍解码", () => {
    expect(
      decode({
        taskId: "materials-trace-1",
        seq: 30,
        type: "tool_call",
        agent_path: "main",
        data: { tool: "search", query: "光合作用 光反应", result_count: 3, stage: "research" },
      }),
    ).toMatchObject({ kind: "tool_call", name: "search", agentPath: "main" });
    expect(
      decode({
        taskId: "materials-trace-1",
        seq: 31,
        type: "tool_call",
        agent_path: "fill:sec-1",
        data: { tool: "llm", stage: "fill", sec_id: "sec-1", error: "llm_request_failed" },
      }),
    ).toMatchObject({ kind: "tool_call", name: "llm", agentPath: "fill:sec-1" });
  });

  it("StudyTaskTracePage 对齐后端 key-set：events / next_after_seq / has_more", () => {
    const page: StudyTaskTracePage = { events: [], next_after_seq: 42, has_more: false };
    // @ts-expect-error 旧契约（count?/next_after_seq?）不再合法：has_more 必填且无 count 字段
    const legacy: StudyTaskTracePage = { events: [], count: 1 };
    expect(Object.keys(page).sort()).toEqual(["events", "has_more", "next_after_seq"]);
    expect(legacy).toBeTruthy();
  });

  it("section_fill 状态徽标映射后端词表 start|ok|retry|failed", () => {
    expect(sectionStatusText("start")).toBe("撰写中");
    expect(sectionStatusText("ok")).toBe("已完成");
    expect(sectionStatusText("retry")).toBe("重试中");
    expect(sectionStatusText("failed")).toBe("失败");
  });
});
