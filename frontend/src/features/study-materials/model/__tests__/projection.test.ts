import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeStudyEvent } from "../../streaming/contract";
import {
  initialStudyProjection,
  normalizeStudyResult,
  studyProjectionReducer,
  type StudyProjectionState,
} from "../reducer";
import {
  selectKnowledgePointBoard,
  selectStageNodes,
  selectStatusLine,
  selectTimelineFoldSummary,
  selectTimelineGroups,
} from "../selectors";
import { degradedRevisionStream, type StudyMaterialsWireEvent } from "../../streaming/__fixtures__/study-materials-streams";

interface WireEvent {
  type: string;
  data?: Record<string, unknown>;
  seq?: number;
  taskId?: string;
}

/** legacy AgentCore 流：task_started → thinking → 检索工具 → subagent → done（material 无内联 markdown）。 */
const legacyStream: WireEvent[] = [
  { type: "task_started", seq: 1, taskId: "t-1", data: { taskId: "t-1", query: "函数单调性", subject: "高中数学" } },
  { type: "status", seq: 2, data: { content: "规划学习路径…" } },
  { type: "thinking", seq: 3, data: { content: "我先梳理函数单调性的知识结构", delta: true } },
  { type: "thinking", seq: 4, data: { content: "，拆出 4 个知识点。", delta: true } },
  {
    type: "tool_call",
    seq: 5,
    data: { step_id: "s-1", name: "split_knowledge_points", title: "拆分知识点", arguments: { topic: "函数单调性" } },
  },
  {
    type: "tool_result",
    seq: 6,
    data: {
      step_id: "s-1",
      name: "split_knowledge_points",
      success: true,
      elapsed_ms: 8200,
      output: { knowledge_points: [{ title: "定义" }, { title: "判定" }, { title: "复合" }, { title: "误区" }] },
    },
  },
  {
    type: "tool_call",
    seq: 7,
    data: { step_id: "s-2", name: "web_search_knowledge", arguments: { queries: ["函数单调性 定义"] } },
  },
  { type: "subagent_start", seq: 8, data: { knowledge_point: "定义与判定" } },
  {
    type: "tool_result",
    seq: 9,
    data: { step_id: "s-2", name: "web_search_knowledge", success: true, output: { results: [{ title: "a", url: "u" }] } },
  },
  { type: "subagent_end", seq: 10, data: { knowledge_point: "定义与判定" } },
  {
    type: "done",
    seq: 11,
    data: {
      material: {
        topic: "函数单调性",
        md_url: "/api/media/generated/m.md",
        md_filename: "m.md",
        pdf_url: "/api/media/generated/m.pdf",
        iteration: 1,
        passed: true,
        issues: [],
        error: null,
      },
      per_kp_report: [],
      timing_report: {},
    },
  },
];

/** codex staged workflow 流：workflow_stage + 快照 text_delta + 内联 markdown 的 done。 */
const codexStream: WireEvent[] = [
  { type: "task_started", seq: 1, taskId: "t-2", data: { taskId: "t-2", query: "牛顿第二定律", subject: "高中物理" } },
  { type: "workflow_stage", seq: 2, data: { stage: "plan", last_successful_stage: "", revision_attempts: 0 } },
  { type: "reasoning_delta", seq: 3, data: { content: "规划知识点…" } },
  { type: "workflow_stage", seq: 4, data: { stage: "draft", last_successful_stage: "research", revision_attempts: 0 } },
  { type: "text_delta", seq: 5, data: { content: "# 牛顿第二定律\n\n完整快照" } },
  {
    type: "done",
    seq: 6,
    data: {
      success: true,
      material: { topic: "牛顿第二定律", subject: "高中物理", markdown: "# 牛顿第二定律\n\n完整快照", passed: true, issues: [] },
      quality_report: { passed: true, failed_checks: [] },
    },
  },
];

function project(events: WireEvent[], startAt = 1_000): StudyProjectionState {
  let state = initialStudyProjection();
  let at = startAt;
  for (const raw of events) {
    const normalized = normalizeEvent(raw);
    if (!normalized) continue;
    const decoded = decodeStudyEvent(normalized);
    if (!decoded) continue;
    state = studyProjectionReducer(state, { type: "event", event: decoded, at });
    at += 100;
  }
  return state;
}

/** 固定 wire fixture 的投影入口（与 reducer.test 同一约定）。 */
function projectWire(events: StudyMaterialsWireEvent[]): StudyProjectionState {
  let state = initialStudyProjection();
  let at = 1_000;
  for (const raw of events) {
    const normalized = normalizeEvent(raw);
    if (!normalized) continue;
    const decoded = decodeStudyEvent(normalized);
    if (!decoded) continue;
    state = studyProjectionReducer(state, {
      type: "event",
      event: decoded,
      seq: normalized.seq,
      at,
    });
    at += 100;
  }
  return state;
}

function settle(
  state: StudyProjectionState,
  reason: "completed" | "eof" | "aborted" | "error",
  at = 100_000,
  error?: string,
): StudyProjectionState {
  return studyProjectionReducer(state, { type: "settled", reason, at, ...(error ? { error } : {}) });
}

describe("study projection：legacy AgentCore 流", () => {
  it("thinking 增量追加，工具按 step_id 配对并按阶段分组", () => {
    const state = project(legacyStream.slice(0, 10)); // 截至 subagent_end，未含 done
    expect(state.turn.thinking?.text).toBe("我先梳理函数单调性的知识结构，拆出 4 个知识点。");
    expect(state.turn.thinking?.status).toBe("streaming");

    const plan = state.turn.tools.find((t) => t.id === "s-1");
    expect(plan?.status).toBe("success");
    expect(plan?.summary).toBe("拆出 4 个知识点");
    expect(plan?.elapsedMs).toBe(8200);
    expect(plan?.stage).toBe("plan");

    const groups = selectTimelineGroups(state.turn);
    expect(groups.map((g) => g.stage)).toEqual(["plan", "research"]);
    expect(groups[0].status).toBe("success");
    expect(groups[1].status).toBe("success");
  });

  it("subagent 事件驱动 KP chips 状态", () => {
    const state = project(legacyStream);
    expect(state.turn.kpItems).toEqual([{ title: "定义与判定", status: "done" }]);
  });

  it("done（material 无内联 markdown）→ done 态；eof 是正常完成", () => {
    const state = settle(project(legacyStream), "eof");
    expect(state.turn.runStatus).toBe("done");
    expect(state.turn.result?.topic).toBe("函数单调性");
    expect(state.turn.result?.markdown).toBeUndefined();
    expect(state.turn.result?.mdUrl).toBe("/api/media/generated/m.md");
    expect(state.turn.result?.pdfUrl).toBe("/api/media/generated/m.pdf");
    expect(state.turn.thinking?.status).toBe("done");
    expect(selectTimelineFoldSummary(state.turn)).toBe("2 个工具调用全部完成");
  });

  it("阶段步进器：done 后经过的阶段全部标记完成", () => {
    const state = settle(project(legacyStream), "eof");
    const nodes = selectStageNodes(state.turn);
    expect(nodes.find((n) => n.key === "plan")?.state).toBe("done");
    expect(nodes.find((n) => n.key === "research")?.state).toBe("done");
    expect(nodes.find((n) => n.key === "export")?.state).toBe("todo");
  });
});

describe("study projection：codex staged workflow 流", () => {
  it("reasoning_delta 归入 thinking；text_delta 为替换语义快照", () => {
    const state = project(codexStream);
    expect(state.turn.thinking?.text).toBe("规划知识点…");
    expect(state.turn.snapshotMarkdown).toContain("完整快照");
    expect(state.turn.currentStage).toBe("write");
  });

  it("done 内联 markdown 与 quality_report 进入投影", () => {
    const state = settle(project(codexStream), "eof");
    expect(state.turn.runStatus).toBe("done");
    expect(state.turn.result?.markdown).toContain("牛顿第二定律");
    expect(state.turn.qualityReport?.passed).toBe(true);
  });
});

describe("study projection：中断与失败", () => {
  const partialStream = legacyStream.slice(0, 8);

  it("aborted → interrupted，运行中工具标记 interrupted", () => {
    const running = project(partialStream);
    expect(running.turn.tools.some((t) => t.status === "running")).toBe(true);
    const state = settle(running, "aborted");
    expect(state.turn.runStatus).toBe("interrupted");
    expect(state.turn.tools.every((t) => t.status !== "running")).toBe(true);
    expect(state.turn.tools.find((t) => t.id === "s-2")?.status).toBe("interrupted");
  });

  it("eof 且未见 done → interrupted（意外中断）", () => {
    const state = settle(project(partialStream), "eof");
    expect(state.turn.runStatus).toBe("interrupted");
  });

  it("error 事件 → error 态并保留信息", () => {
    const withError = studyProjectionReducer(project(partialStream), {
      type: "event",
      event: { kind: "error", message: "llm_request_failed" },
      at: 5_000,
    });
    const state = settle(withError, "eof");
    expect(state.turn.runStatus).toBe("error");
    expect(state.turn.errorMessage).toBe("llm_request_failed");
    expect(state.turn.tools.find((t) => t.id === "s-2")?.status).toBe("error");
  });

  it("传输层 error → interrupted 并保留错误描述", () => {
    const state = settle(project(partialStream), "error", 100_000, "网络连接中断");
    expect(state.turn.runStatus).toBe("interrupted");
    expect(state.turn.errorMessage).toBe("网络连接中断");
  });

  it("status 事件驱动状态行；无 status 时回退到运行中工具", () => {
    const state = project(partialStream);
    expect(selectStatusLine(state.turn)).toBe("规划学习路径…");
    const noStatus = project(partialStream.slice(2));
    expect(selectStatusLine(noStatus.turn)).toContain("联网搜索相关学习资料");
  });
});

describe("normalizeStudyResult", () => {
  it("兼容 material 嵌套在 result 下的载荷", () => {
    const r = normalizeStudyResult({ result: { material: { topic: "x", md_url: "/m.md" } } });
    expect(r.topic).toBe("x");
    expect(r.mdUrl).toBe("/m.md");
  });

  it("导出续传：md_url 在顶层也能取到", () => {
    const r = normalizeStudyResult({ material: { topic: "x", markdown: "# 稿" }, md_url: "/new.md" });
    expect(r.markdown).toBe("# 稿");
    expect(r.mdUrl).toBe("/new.md");
  });
});

describe("selectKnowledgePointBoard", () => {
  it("检索中用实时 kpItems，无质量数据时来源信息为空", () => {
    const state = project(legacyStream.slice(0, 9)); // 截至 web_search 结果，subagent 仍在
    const board = selectKnowledgePointBoard(state);
    expect(board.serverReported).toBe(false);
    expect(board.items).toEqual([
      { key: "定义与判定", title: "定义与判定", status: "running", sourceClasses: [], failedChecks: [] },
    ]);
    expect(board.failedChecks).toEqual([]);
  });

  it("quality_report.per_knowledge_point 到达后合并来源统计与失败检查", () => {
    const state = projectWire(degradedRevisionStream.slice(0, 7));
    const board = selectKnowledgePointBoard(state);
    expect(board.serverReported).toBe(false);
    const kp = board.items.find((item) => item.key === "kp-1");
    // kp-1 与 kpItems[0] 对齐，标题回到中文知识点名。
    expect(kp?.title).toBe("定义与判定");
    expect(kp?.passed).toBe(false);
    expect(kp?.sourceCount).toBe(1);
    expect(kp?.sourceClasses).toEqual(["web"]);
    expect(kp?.failedChecks).toEqual(["research_evidence_missing:kp-1"]);
    expect(board.failedChecks).toEqual(["research_evidence_missing:kp-1"]);
  });

  it("hydrate_server_state 回填后标注服务端快照", () => {
    const base = project(legacyStream.slice(0, 2)); // 尚无 kpItems 与 quality_report
    const hydrated = studyProjectionReducer(base, {
      type: "hydrate_server_state",
      perKpState: {
        定义与判定: { knowledge_point: "定义与判定", search: true, aggregate: false, write: false, web_results: 3 },
      },
      searchSummaryByKp: {
        定义与判定: { provider: "web", query: "函数单调性 定义", results: [{ title: "a", url: "u" }] },
      },
    });
    const board = selectKnowledgePointBoard(hydrated);
    expect(board.serverReported).toBe(true);
    expect(board.items).toHaveLength(1);
    expect(board.items[0]).toMatchObject({
      title: "定义与判定",
      status: "done",
      sourceCount: 3,
      sourceClasses: ["web"],
    });

    // 实时 kpItems 出现后优先于服务端快照。
    const withLive = project(legacyStream.slice(0, 9));
    const merged = studyProjectionReducer(withLive, {
      type: "hydrate_server_state",
      perKpState: { 定义与判定: { search: true, aggregate: true, write: false, web_results: 3 } },
    });
    expect(selectKnowledgePointBoard(merged).serverReported).toBe(false);
  });
});
