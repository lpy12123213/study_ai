import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeStudyMaterialsEvent } from "../../streaming/contract";
import {
  codexSnapshotStream,
  continuationChildStart,
  legacyStudyMaterialsStream,
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
});
