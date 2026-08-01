import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeStudyMaterialsEvent } from "../../streaming/contract";
import {
  codexSnapshotStream,
  continuationChildStart,
  degradedRevisionStream,
  legacyStudyMaterialsStream,
  parallelTaggedStream,
} from "../../streaming/__fixtures__/study-materials-streams";

function decode(raw: Record<string, unknown>) {
  const normalized = normalizeEvent(raw);
  if (!normalized) throw new Error("fixture did not normalize");
  return decodeStudyMaterialsEvent(normalized);
}

describe("study-materials stream contract", () => {
  it("解码 legacy thinking / step_id / output / elapsed_ms", () => {
    expect(decode(legacyStudyMaterialsStream[2])).toEqual({
      kind: "thinking",
      content: "先拆分定义、判定方法与典型误区。",
    });
    expect(decode(legacyStudyMaterialsStream[4])).toMatchObject({
      kind: "tool_result",
      stepId: "split-1",
      name: "split_knowledge_points",
      success: true,
      elapsedMs: 820,
      result: { knowledge_points: ["定义与判定", "复合函数单调性", "常见误区"] },
    });
  });

  it("解码 Codex reasoning_delta / id / content / is_error", () => {
    expect(decode(codexSnapshotStream[2])).toEqual({
      kind: "thinking",
      content: "先验证力、质量、加速度的条件。",
    });
    expect(decode(codexSnapshotStream[4])).toMatchObject({
      kind: "tool_result",
      stepId: "codex-web-1",
      success: true,
      result: {
        success: true,
        results: [{ title: "Newton's second law", url: "https://example.org/newton" }],
      },
    });
  });

  it("continue 的首事件切换到新 taskId 并保留 parentTaskId", () => {
    expect(decode(continuationChildStart)).toMatchObject({
      kind: "task_started",
      taskId: "materials-child-2",
      parentTaskId: "materials-parent-1",
    });
  });

  it("解码打标 subagent_start：subagentId/index/total/agentKind 透传", () => {
    expect(decode(parallelTaggedStream[2])).toMatchObject({
      kind: "subagent_start",
      knowledgePoint: "光反应",
      subagentId: "sa-1",
      index: 1,
      total: 3,
      agentKind: "knowledge_research",
    });
  });

  it("解码打标 tool_call/tool_result：subagentId + knowledgePoint 透传", () => {
    expect(decode(parallelTaggedStream[5])).toMatchObject({
      kind: "tool_call",
      stepId: "sa1-web-1",
      name: "web_search_knowledge",
      subagentId: "sa-1",
      knowledgePoint: "光反应",
    });
    expect(decode(parallelTaggedStream[7])).toMatchObject({
      kind: "tool_result",
      stepId: "sa1-web-1",
      success: true,
      subagentId: "sa-1",
      knowledgePoint: "光反应",
    });
  });

  it("legacy 无新字段事件不注入 subagent 字段且非空", () => {
    const start = decode(degradedRevisionStream[2]);
    expect(start).toEqual({ kind: "subagent_start", knowledgePoint: "定义与判定" });
    expect(start).not.toHaveProperty("subagentId");
    expect(start).not.toHaveProperty("index");
    expect(start).not.toHaveProperty("total");
    expect(start).not.toHaveProperty("agentKind");
    const toolCall = decode(legacyStudyMaterialsStream[3]);
    expect(toolCall).toMatchObject({ kind: "tool_call", stepId: "split-1" });
    expect(toolCall).not.toHaveProperty("subagentId");
    expect(toolCall).not.toHaveProperty("knowledgePoint");
  });
});
