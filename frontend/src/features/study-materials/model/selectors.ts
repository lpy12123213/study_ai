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
