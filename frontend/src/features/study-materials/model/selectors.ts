import type { StudyMaterialResult } from "@/shared/api/types";
import type {
  StudyMaterialsProjection,
  StudyMaterialsTurnView,
  StudyMaterialsToolView,
} from "./types";
import {
  STUDY_STAGE_LABELS,
  STUDY_STAGE_ORDER,
  type StudyStageKey,
} from "./stages";

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
}

function asCount(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function selectMaterialResult(state: StudyMaterialsProjection): StudyMaterialResult["material"] | undefined {
  return state.result?.material;
}

export function selectResultMarkdown(state: StudyMaterialsProjection): string {
  return state.result?.material?.markdown || state.markdownSnapshot;
}

export function selectStageSummary(state: StudyMaterialsProjection): string {
  const success = state.stages.filter((stage) => stage.status === "success").length;
  const failed = state.stages.find((stage) => stage.status === "error");
  if (state.runStatus === "done") {
    return success === state.stages.length
      ? `${state.stages.length} 个阶段全部完成`
      : `生成完成 · 已观测 ${success} / ${state.stages.length} 个阶段`;
  }
  if (failed) return `${failed.label}阶段失败`;
  const running = state.stages.find((stage) => stage.status === "running");
  return running ? `正在${running.label}` : `已完成 ${success} / ${state.stages.length} 个阶段`;
}

export function selectToolCount(state: StudyMaterialsProjection): number {
  return state.turn.iterations.reduce((total, iteration) => total + iteration.tools.length, 0);
}

export interface KnowledgePointBoardItem {
  key: string;
  title: string;
  status: "running" | "done" | "error";
  passed?: boolean;
  sourceCount?: number;
  sourceClasses: string[];
  failedChecks: string[];
}

export interface KnowledgePointBoardView {
  items: KnowledgePointBoardItem[];
  /** quality_report 顶层 failed_checks（未按知识点拆分的部分也在这里）。 */
  failedChecks: string[];
  /** 数据来自 taskStatus 回填（重连场景），不是本次流的实时观测。 */
  serverReported: boolean;
}

/** quality_report.per_knowledge_point 以 kp-N 为键；尽量对回实时 kpItems 的标题。 */
function liveTitleForPointId(
  pointId: string,
  kpItems: StudyMaterialsProjection["turn"]["kpItems"],
): string | undefined {
  const indexed = /^kp-(\d+)$/.exec(pointId);
  if (indexed) {
    const candidate = kpItems[Number(indexed[1]) - 1];
    if (candidate) return candidate.title;
  }
  return kpItems.find((item) => item.title === pointId)?.title;
}

/**
 * 知识点看板：优先 quality_report.per_knowledge_point（审查后），
 * 其次实时 kpItems（检索中），最后退回 taskStatus 回填的服务端快照。
 */
export function selectKnowledgePointBoard(
  state: StudyMaterialsProjection,
): KnowledgePointBoardView {
  const report = asRecord(state.qualityReport);
  const topFailedChecks = asStringList(report?.failed_checks);
  const perKp = asRecord(report?.per_knowledge_point);
  const live = state.turn.kpItems;

  if (perKp && Object.keys(perKp).length > 0) {
    const items = Object.entries(perKp).map(([pointId, raw]) => {
      const entry = asRecord(raw) ?? {};
      const liveTitle = liveTitleForPointId(pointId, live);
      const liveItem = liveTitle ? live.find((item) => item.title === liveTitle) : undefined;
      const failedChecks = asStringList(entry.failed_checks);
      const passed = typeof entry.passed === "boolean" ? entry.passed : undefined;
      return {
        key: pointId,
        title: liveTitle ?? pointId,
        status: liveItem?.status ?? (passed === false ? "error" : "done"),
        ...(passed !== undefined ? { passed } : {}),
        ...(asCount(entry.source_count) !== undefined
          ? { sourceCount: asCount(entry.source_count) }
          : {}),
        sourceClasses: asStringList(entry.source_classes),
        failedChecks,
      } satisfies KnowledgePointBoardItem;
    });
    return { items, failedChecks: topFailedChecks, serverReported: false };
  }

  if (live.length > 0) {
    return {
      items: live.map((item) => ({
        key: item.title,
        title: item.title,
        status: item.status,
        sourceClasses: [],
        failedChecks: [],
      })),
      failedChecks: topFailedChecks,
      serverReported: false,
    };
  }

  const coverage = state.serverKpCoverage;
  const serverPerKp = asRecord(coverage?.perKpState);
  const serverSearch = asRecord(coverage?.searchSummaryByKp);
  const keys = [
    ...new Set([...Object.keys(serverPerKp ?? {}), ...Object.keys(serverSearch ?? {})]),
  ];
  if (keys.length > 0) {
    const items = keys.map((kp) => {
      const kpState = asRecord(serverPerKp?.[kp]);
      const search = asRecord(serverSearch?.[kp]);
      const results = Array.isArray(search?.results) ? search.results.length : undefined;
      const sourceCount = asCount(kpState?.web_results) ?? results;
      const provider = typeof search?.provider === "string" && search.provider.trim()
        ? search.provider.trim()
        : undefined;
      const covered = kpState
        ? Boolean(kpState.search || kpState.aggregate || kpState.write)
        : Boolean(sourceCount);
      return {
        key: kp,
        title: kp,
        status: covered ? ("done" as const) : ("running" as const),
        ...(sourceCount !== undefined ? { sourceCount } : {}),
        sourceClasses: provider ? [provider] : [],
        failedChecks: [],
      } satisfies KnowledgePointBoardItem;
    });
    return { items, failedChecks: topFailedChecks, serverReported: true };
  }

  return { items: [], failedChecks: topFailedChecks, serverReported: false };
}

export interface StudyTimelineGroup {
  stage: StudyStageKey;
  label: string;
  status: "queued" | "running" | "success" | "error" | "interrupted";
  tools: StudyMaterialsToolView[];
}

export function selectTimelineGroups(turn: StudyMaterialsTurnView): StudyTimelineGroup[] {
  return STUDY_STAGE_ORDER.flatMap((stage) => {
    const tools = turn.tools.filter((tool) => tool.stage === stage);
    if (tools.length === 0) return [];
    const status = tools.some((tool) => tool.status === "running" || tool.status === "queued")
      ? "running"
      : tools.some((tool) => tool.status === "error")
        ? "error"
        : tools.some((tool) => tool.status === "interrupted")
          ? "interrupted"
          : "success";
    return [{ stage, label: STUDY_STAGE_LABELS[stage], status, tools }];
  });
}

export function selectTimelineFoldSummary(turn: StudyMaterialsTurnView): string {
  const total = turn.tools.length;
  if (total === 0) return "暂无工具调用";
  const failed = turn.tools.filter((tool) => tool.status === "error").length;
  const active = turn.tools.filter((tool) => tool.status === "running" || tool.status === "queued").length;
  if (failed > 0) return `${total} 个工具调用 · ${failed} 个失败`;
  if (active > 0) return `${total} 个工具调用 · ${active} 个进行中`;
  return `${total} 个工具调用全部完成`;
}

export function selectStatusLine(turn: StudyMaterialsTurnView): string {
  if (turn.statusText) return turn.statusText;
  const active = [...turn.tools].reverse().find((tool) => tool.status === "running" || tool.status === "queued");
  if (active) return `正在执行：${active.displayName}`;
  return turn.runStatus === "done" ? "讲义已生成" : "正在准备生成任务…";
}

export interface StudyStageNode {
  key: StudyStageKey;
  label: string;
  state: "todo" | "running" | "done" | "error";
}

export function selectStageNodes(turn: StudyMaterialsTurnView): StudyStageNode[] {
  const groups = new Map(selectTimelineGroups(turn).map((group) => [group.stage, group]));
  return STUDY_STAGE_ORDER.map((stage) => {
    const group = groups.get(stage);
    let state: StudyStageNode["state"] = "todo";
    if (group?.status === "error") state = "error";
    else if (group?.status === "running" || turn.currentStage === stage && turn.runStatus === "streaming") state = "running";
    else if (group && group.status !== "queued") state = "done";
    else if (turn.currentStage === stage && turn.runStatus === "done") state = "done";
    return { key: stage, label: STUDY_STAGE_LABELS[stage], state };
  });
}
