import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import {
  initialStudyMaterialsProjection,
  studyMaterialsProjectionReducer,
  type StudyMaterialsStreamEndReason,
} from "../reducer";
import { selectStageSummary } from "../selectors";
import { decodeStudyMaterialsEvent } from "../../streaming/contract";
import {
  codexSnapshotStream,
  continuationChildStart,
  failedRecoveryStream,
  legacyStudyMaterialsStream,
  type StudyMaterialsWireEvent,
} from "../../streaming/__fixtures__/study-materials-streams";

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

function settle(
  state: ReturnType<typeof initialStudyMaterialsProjection>,
  reason: StudyMaterialsStreamEndReason,
) {
  return studyMaterialsProjectionReducer(state, {
    type: "settled",
    reason,
    at: 10_000,
  });
}

describe("study-materials projection reducer", () => {
  it("legacy 工具按阶段投影并在 done 后得到完成结果", () => {
    const state = project(legacyStudyMaterialsStream);
    expect(state.runStatus).toBe("done");
    expect(state.taskId).toBe("materials-legacy-1");
    expect(state.turn.thinking?.text).toContain("定义、判定方法");
    expect(state.stages.find((stage) => stage.id === "plan")?.status).toBe("success");
    expect(state.stages.find((stage) => stage.id === "research")?.status).toBe("success");
    expect(state.stages.find((stage) => stage.id === "export")?.status).toBe("pending");
    expect(selectStageSummary(state)).toBe("生成完成 · 已观测 2 / 6 个阶段");
    expect(state.turn.iterations.map((iteration) => iteration.label)).toEqual([
      "规划",
      "检索与研究",
    ]);
    expect(state.result?.material?.markdown).toContain("# 函数单调性");
  });

  it("text_delta 使用完整快照替换语义，不拼接两个版本", () => {
    const beforeDone = project(codexSnapshotStream.slice(0, -1));
    expect(beforeDone.markdownSnapshot).toBe("# 第二版\n\n修订后的完整草稿。");
    expect(beforeDone.markdownSnapshot).not.toContain("第一版");
  });

  it("失败事件保留可恢复信息并标记当前阶段", () => {
    const state = project(failedRecoveryStream);
    expect(state.runStatus).toBe("failed");
    expect(state.currentStage).toBe("research");
    expect(state.recovery).toMatchObject({
      stage: "research",
      code: "quality_gate_not_met",
      recoverable: true,
    });
    expect(state.recovery?.issues).toEqual(["来源覆盖不足"]);
  });

  it("普通 EOF/Abort 没有终态事件时只标记 interrupted", () => {
    const running = project(legacyStudyMaterialsStream.slice(0, 5));
    expect(settle(running, "eof").runStatus).toBe("interrupted");
    expect(settle(running, "aborted").turn.runStatus).toBe("interrupted");
  });

  it("已收到 done 后 transport EOF 不会把完成态降级为中断", () => {
    const done = project(legacyStudyMaterialsStream);
    expect(settle(done, "eof").runStatus).toBe("done");
  });

  it("continue 子任务首事件切换 taskId", () => {
    const parent = project(legacyStudyMaterialsStream);
    const normalized = normalizeEvent(continuationChildStart);
    if (!normalized) throw new Error("fixture did not normalize");
    const event = decodeStudyMaterialsEvent(normalized);
    if (!event) throw new Error("fixture did not decode");
    const child = studyMaterialsProjectionReducer(parent, {
      type: "event",
      event,
      seq: normalized.seq,
      at: 12_000,
    });
    expect(child.taskId).toBe("materials-child-2");
    expect(child.parentTaskId).toBe("materials-parent-1");
    expect(child.runStatus).toBe("running");
  });
});
