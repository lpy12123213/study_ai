import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeStudyMaterialsEvent } from "../../streaming/contract";
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
    expect(decode(traceStream[7])).toMatchObject({
      kind: "figure_trace",
      figureId: "fig-1",
      stage: "render",
      status: "success",
      agentPath: "fig:1",
    });
    expect(decode(traceStream[8])).toEqual({
      kind: "section_fill",
      secId: "sec-1",
      status: "done",
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
      expect.objectContaining({ kind: "figure", figureId: "fig-1", stage: "render" }),
    ]);
  });

  it("section_fill 更新每节状态", () => {
    const state = project(traceStream);
    expect(state.sectionStatus).toEqual({ "sec-1": "done" });
  });

  it("legacy 流不产生 todos/trace 切片（旧任务回放不回归）", () => {
    const state = project(legacyStudyMaterialsStream);
    expect(state.todos).toEqual({});
    expect(state.traceByAgent).toEqual({});
    expect(state.sectionStatus).toEqual({});
  });
});
