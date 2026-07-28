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
  degradedRevisionStream,
  failedRecoveryStream,
  legacyStudyMaterialsStream,
  researchOutageStream,
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

  it("text_snapshot 递增 snapshotVersion，与快照替换语义一致", () => {
    const state = project(codexSnapshotStream.slice(0, -1));
    expect(state.snapshotVersion).toBe(2);
    expect(state.markdownSnapshot).toContain("第二版");
  });

  it("workflow_stage 摘掉当前阶段的推断标注，工具推断保持不变", () => {
    const codex = project(codexSnapshotStream);
    expect(codex.stages.find((stage) => stage.id === "research")?.inferred).toBe(false);
    // plan 由 workflow_stage 前置完成，但没有自己的权威事件，仍是推断。
    expect(codex.stages.find((stage) => stage.id === "plan")?.inferred).toBe(true);

    const legacy = project(legacyStudyMaterialsStream);
    expect(legacy.stages.every((stage) => stage.inferred)).toBe(true);
  });

  it("revision_required 保留剩余修订次数，quality_degraded 不覆盖它", () => {
    const retrying = project(degradedRevisionStream.slice(0, 7));
    expect(retrying.revisionIssues).toEqual(["「定义与判定」检索证据不足"]);
    expect(retrying.remainingRevisionAttempts).toBe(2);
    expect(retrying.researchRetry).toEqual({ pointIds: ["kp-1"], attempt: 1, remainingAttempts: 1 });

    // quality_degraded 携带的是已用修订次数，不能覆盖 remainingAttempts。
    const degraded = project(degradedRevisionStream.slice(0, 10));
    expect(degraded.revisionIssues).toEqual(["「定义与判定」来源类型单一"]);
    expect(degraded.remainingRevisionAttempts).toBe(2);
  });

  it("degraded done 保留 issues 与 quality_report，runStatus 仍为 done", () => {
    const state = project(degradedRevisionStream);
    expect(state.runStatus).toBe("done");
    expect(state.result?.degraded).toBe(true);
    expect(state.result?.material?.passed).toBe(false);
    expect(state.result?.material?.issues).toEqual(["「定义与判定」来源类型单一"]);
    expect(state.qualityReport?.failed_checks).toEqual(["source_classes_missing:kp-1"]);
    expect(state.researchRetry).toBeUndefined();
  });

  it("research_tool_outage 恢复码原样保留，供 UI 区分文案", () => {
    const state = project(researchOutageStream);
    expect(state.runStatus).toBe("failed");
    expect(state.recovery?.code).toBe("research_tool_outage");
    expect(state.recovery?.recoverable).toBe(true);
  });

  it("服务端取消确认后 settled 文案区分", () => {
    const running = project(legacyStudyMaterialsStream.slice(0, 5));
    const stopping = studyMaterialsProjectionReducer(running, { type: "stop_requested", at: 9_000 });
    const confirmed = studyMaterialsProjectionReducer(stopping, {
      type: "server_cancel_confirmed",
      at: 9_100,
    });
    expect(settle(confirmed, "aborted").statusText).toBe("已停止，服务端任务已取消");
    expect(settle(stopping, "aborted").statusText).toBe("已停止接收；服务端任务可能仍在继续");
  });

  it("begin_continuation 快照上一版成果；done 清除；restore 还原", () => {
    const done = project(legacyStudyMaterialsStream);
    const continued = studyMaterialsProjectionReducer(done, { type: "begin_continuation" });
    expect(continued.runStatus).toBe("idle");
    expect(continued.result).toBeUndefined();
    expect(continued.previousResult?.result.material?.topic).toContain("函数单调性");
    expect(continued.previousResult?.markdownSnapshot).toContain("# 函数单调性");
    expect(continued.previousResult?.taskId).toBe("materials-legacy-1");

    const restored = studyMaterialsProjectionReducer(continued, {
      type: "restore_previous_result",
      at: 14_000,
    });
    expect(restored.runStatus).toBe("done");
    expect(restored.result?.material?.topic).toContain("函数单调性");
    expect(restored.taskId).toBe("materials-legacy-1");
    expect(restored.statusText).toBe("已还原上一版成果");
    expect(restored.previousResult).toBeUndefined();

    // 新一轮完成（子任务 done）清除上一版快照。
    const redone = studyMaterialsProjectionReducer(continued, {
      type: "event",
      event: {
        kind: "done",
        result: { material: { topic: "函数单调性 · 第二版", markdown: "# 新稿", passed: true } },
      },
      seq: 1,
      at: 15_000,
    });
    expect(redone.previousResult).toBeUndefined();
    expect(redone.runStatus).toBe("done");
  });

  it("没有成果时 begin_continuation 不产生上一版快照", () => {
    const running = project(legacyStudyMaterialsStream.slice(0, 5));
    const continued = studyMaterialsProjectionReducer(running, { type: "begin_continuation" });
    expect(continued.previousResult).toBeUndefined();
  });
});
