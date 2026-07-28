import type {
  ToolIterationView,
  ToolStepStatus,
  ToolStepView,
} from "@/features/chat/model/types";
import type { StudyMaterialsStreamEvent } from "../streaming/contract";
import type {
  NormalizedStudyResult,
  StudyMaterialsProjection,
  StudyMaterialsRecoveryView,
  StudyMaterialsStageId,
  StudyMaterialsStageView,
  StudyMaterialsToolView,
  StudyMaterialsTurnView,
} from "./types";
import {
  STUDY_STAGE_LABELS,
  STUDY_STAGE_ORDER,
  inferStageFromTool,
  studyStageFromFailure,
  studyStageFromWorkflow,
  type StudyStageKey,
} from "./stages";
import {
  studyToolDisplayName,
  studyToolIntent,
  summarizeStudyToolResult,
} from "./tool-adapters";

export type StudyMaterialsStreamEndReason = "completed" | "eof" | "aborted" | "error";

export type StudyMaterialsProjectionAction =
  | { type: "reset" }
  | { type: "event"; event: StudyMaterialsStreamEvent; seq?: number; at: number }
  | { type: "stop_requested"; at: number }
  | { type: "settled"; reason: StudyMaterialsStreamEndReason; at: number; error?: Error | string };

export const STUDY_MATERIALS_STAGES: ReadonlyArray<{
  id: StudyMaterialsStageId;
  label: string;
}> = STUDY_STAGE_ORDER.map((id) => ({ id, label: STUDY_STAGE_LABELS[id] }));

const STAGE_INDEX = new Map(STUDY_MATERIALS_STAGES.map((stage, index) => [stage.id, index]));

export function inferStudyMaterialsStage(toolName: string): StudyMaterialsStageId | undefined {
  return inferStageFromTool(toolName) || undefined;
}

export function mapWorkflowStage(stage: string): StudyMaterialsStageId | undefined {
  return studyStageFromWorkflow(stage) || undefined;
}

export function initialStudyMaterialsProjection(): StudyMaterialsProjection {
  return {
    runStatus: "idle",
    lastSeq: 0,
    statusText: "",
    stages: STUDY_MATERIALS_STAGES.map(
      ({ id, label }): StudyMaterialsStageView => ({ id, label, status: "pending", inferred: true }),
    ),
    turn: {
      runStatus: "idle",
      interimText: "",
      iterations: [],
      finalText: "",
      tools: [],
      kpItems: [],
      snapshotMarkdown: "",
      statusText: "",
    },
    markdownSnapshot: "",
    revisionIssues: [],
    seenTerminal: false,
    stopIntent: false,
  };
}

function stageLabel(stage: StudyMaterialsStageId): string {
  return STUDY_MATERIALS_STAGES.find((item) => item.id === stage)?.label ?? stage;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
}

/** done 载荷可能是 data、data.result，下载链接也可能位于 material 外层。 */
export function normalizeStudyResult(value: unknown): NormalizedStudyResult {
  const root = asRecord(value) ?? {};
  const nestedResult = asRecord(root.result);
  const payload = nestedResult ?? root;
  const material = asRecord(payload.material) ?? {};
  return {
    ...(asString(material.topic) ? { topic: asString(material.topic) } : {}),
    ...(asString(material.subject) ? { subject: asString(material.subject) } : {}),
    ...(asString(material.markdown) ? { markdown: asString(material.markdown) } : {}),
    ...(typeof material.passed === "boolean" ? { passed: material.passed } : {}),
    issues: asStringList(material.issues),
    ...(asString(material.md_url) ?? asString(payload.md_url)
      ? { mdUrl: asString(material.md_url) ?? asString(payload.md_url) }
      : {}),
    ...(asString(material.md_filename) ?? asString(payload.md_filename)
      ? { mdFilename: asString(material.md_filename) ?? asString(payload.md_filename) }
      : {}),
    ...(asString(material.tex_url) ?? asString(payload.tex_url)
      ? { texUrl: asString(material.tex_url) ?? asString(payload.tex_url) }
      : {}),
    ...(asString(material.tex_filename) ?? asString(payload.tex_filename)
      ? { texFilename: asString(material.tex_filename) ?? asString(payload.tex_filename) }
      : {}),
    ...(asString(material.pdf_url) ?? asString(payload.pdf_url)
      ? { pdfUrl: asString(material.pdf_url) ?? asString(payload.pdf_url) }
      : {}),
    ...(asString(material.pdf_filename) ?? asString(payload.pdf_filename)
      ? { pdfFilename: asString(material.pdf_filename) ?? asString(payload.pdf_filename) }
      : {}),
    ...(asString(material.expires_at) ?? asString(payload.expires_at)
      ? { expiresAt: asString(material.expires_at) ?? asString(payload.expires_at) }
      : {}),
    raw: payload as NormalizedStudyResult["raw"],
  };
}

function ensureStageIteration(
  turn: StudyMaterialsTurnView,
  stage: StudyMaterialsStageId,
): StudyMaterialsTurnView {
  const index = (STAGE_INDEX.get(stage) ?? 0) + 1;
  if (turn.iterations.some((iteration) => iteration.index === index)) return turn;
  const created: ToolIterationView = {
    index,
    label: stageLabel(stage),
    status: "queued",
    tools: [],
  };
  return {
    ...turn,
    iterations: [...turn.iterations, created].sort((a, b) => a.index - b.index),
  };
}

function aggregateIterationStatus(tools: ToolStepView[]): ToolStepStatus {
  if (tools.some((tool) => tool.status === "running" || tool.status === "queued")) return "running";
  if (tools.some((tool) => tool.status === "error")) return "error";
  if (tools.some((tool) => tool.status === "interrupted")) return "interrupted";
  return tools.length > 0 ? "success" : "queued";
}

function setCurrentStage(
  state: StudyMaterialsProjection,
  stage: StudyMaterialsStageId,
): StudyMaterialsProjection {
  const currentIndex = STAGE_INDEX.get(stage) ?? 0;
  const stages = state.stages.map((item, index) => {
    if (item.id === stage) return { ...item, status: "running" as const };
    if (index < currentIndex && item.status === "pending") return { ...item, status: "success" as const };
    return item;
  });
  const turn = ensureStageIteration(state.turn, stage);
  return {
    ...state,
    runStatus: "running",
    currentStage: stage,
    stages,
    turn: { ...turn, runStatus: "streaming", currentStage: stage },
  };
}

function patchStageIteration(
  turn: StudyMaterialsTurnView,
  stage: StudyMaterialsStageId,
  patch: (iteration: ToolIterationView) => ToolIterationView,
): StudyMaterialsTurnView {
  const index = (STAGE_INDEX.get(stage) ?? 0) + 1;
  const ensured = ensureStageIteration(turn, stage);
  return {
    ...ensured,
    iterations: ensured.iterations.map((iteration) =>
      iteration.index === index ? patch(iteration) : iteration,
    ),
  };
}

function activeStage(state: StudyMaterialsProjection, toolName?: string): StudyMaterialsStageId {
  return (toolName ? inferStudyMaterialsStage(toolName) : undefined) ?? state.currentStage ?? "plan";
}

function findTool(turn: StudyMaterialsTurnView, stepId: string): ToolStepView | undefined {
  return turn.iterations.flatMap((iteration) => iteration.tools).find((tool) => tool.id === stepId);
}

function patchFlatTool(
  tools: StudyMaterialsToolView[],
  stepId: string,
  patch: (tool: StudyMaterialsToolView | undefined) => StudyMaterialsToolView,
): StudyMaterialsToolView[] {
  const prior = tools.find((tool) => tool.id === stepId);
  const next = patch(prior);
  return prior
    ? tools.map((tool) => (tool.id === stepId ? next : tool))
    : [...tools, next];
}

function markActiveTools(
  turn: StudyMaterialsTurnView,
  status: "error" | "interrupted",
  at: number,
): StudyMaterialsTurnView {
  return {
    ...turn,
    tools: turn.tools.map((tool) =>
      tool.status === "running" || tool.status === "queued"
        ? { ...tool, status, observedResultAt: tool.observedResultAt ?? at }
        : tool,
    ),
    iterations: turn.iterations.map((iteration) => {
      const tools = iteration.tools.map((tool) =>
        tool.status === "running" || tool.status === "queued"
          ? { ...tool, status, observedResultAt: tool.observedResultAt ?? at }
          : tool,
      );
      return {
        ...iteration,
        tools,
        status: aggregateIterationStatus(tools),
        completedAt: iteration.completedAt ?? at,
      };
    }),
  };
}

function markComplete(state: StudyMaterialsProjection, at: number): StudyMaterialsProjection {
  const turn: StudyMaterialsTurnView = {
    ...state.turn,
    runStatus: "done",
    thinking: state.turn.thinking
      ? {
          ...state.turn.thinking,
          status: "done",
          ...(state.startedAt !== undefined ? { durationMs: Math.max(0, at - state.startedAt) } : {}),
        }
      : undefined,
    iterations: state.turn.iterations.map((iteration) => {
      const tools = iteration.tools.map((tool) =>
        tool.status === "running" || tool.status === "queued"
          ? { ...tool, status: "success" as const, observedResultAt: tool.observedResultAt ?? at }
          : tool,
      );
      return {
        ...iteration,
        tools,
        status: aggregateIterationStatus(tools),
        completedAt: iteration.completedAt ?? at,
      };
    }),
    tools: state.turn.tools.map((tool) =>
      tool.status === "running" || tool.status === "queued"
        ? { ...tool, status: "success", observedResultAt: tool.observedResultAt ?? at }
        : tool,
    ),
  };
  const reachedStages = new Set<StudyStageKey>(turn.tools.map((tool) => tool.stage));
  if (state.currentStage) reachedStages.add(state.currentStage);
  return {
    ...state,
    runStatus: "done",
    endedAt: at,
    stages: state.stages.map((stage) =>
      reachedStages.has(stage.id) ? { ...stage, status: "success" } : stage,
    ),
    turn,
  };
}

function recoveryFromEvent(event: Extract<StudyMaterialsStreamEvent, { kind: "recovery_available" }>) {
  const issues = Array.isArray(event.recovery.issues)
    ? event.recovery.issues.filter((item): item is string => typeof item === "string")
    : [];
  const recovery: StudyMaterialsRecoveryView = {
    issues,
    recoverable: event.recovery.recoverable !== false,
  };
  if (typeof event.recovery.stage === "string") recovery.stage = event.recovery.stage;
  if (typeof event.recovery.code === "string") recovery.code = event.recovery.code;
  if (typeof event.recovery.detail === "string") recovery.detail = event.recovery.detail;
  return recovery;
}

function applyEvent(
  state: StudyMaterialsProjection,
  event: StudyMaterialsStreamEvent,
  at: number,
): StudyMaterialsProjection {
  switch (event.kind) {
    case "task_started": {
      const next = setCurrentStage(
        {
          ...state,
          taskId: event.taskId,
          ...(event.parentTaskId ? { parentTaskId: event.parentTaskId } : {}),
          startedAt: state.startedAt ?? at,
          stopIntent: false,
          seenTerminal: false,
        },
        "plan",
      );
      return { ...next, statusText: next.statusText || "正在规划生成任务…" };
    }

    case "status":
      return {
        ...state,
        runStatus: "running",
        statusText: event.content || state.statusText,
        startedAt: state.startedAt ?? at,
        turn: {
          ...state.turn,
          runStatus: "streaming",
          statusText: event.content || state.turn.statusText,
        },
      };

    case "progress": {
      const mapped = event.stage ? mapWorkflowStage(event.stage) : undefined;
      const staged = mapped ? setCurrentStage(state, mapped) : state;
      return {
        ...staged,
        runStatus: "running",
        ...(event.percent !== undefined ? { progress: Math.max(0, Math.min(100, event.percent)) } : {}),
        startedAt: staged.startedAt ?? at,
      };
    }

    case "thinking": {
      if (!event.content) return state;
      const thinking = state.turn.thinking
        ? {
            ...state.turn.thinking,
            text: state.turn.thinking.text + event.content,
            status: "streaming" as const,
          }
        : {
            text: event.content,
            status: "streaming" as const,
            userVisible: true as const,
          };
      return {
        ...state,
        runStatus: "running",
        startedAt: state.startedAt ?? at,
        turn: { ...state.turn, runStatus: "streaming", thinking },
      };
    }

    case "workflow_stage": {
      const stage = mapWorkflowStage(event.stage);
      return stage ? setCurrentStage(state, stage) : state;
    }

    case "tool_call": {
      const stage = activeStage(state, event.name);
      const staged = setCurrentStage(state, stage);
      const tool: ToolStepView = {
        id: event.stepId,
        iteration: (STAGE_INDEX.get(stage) ?? 0) + 1,
        name: event.name,
        displayName: event.title ?? studyToolDisplayName(event.name),
        intent: studyToolIntent(event.name, event.arguments),
        status: "running",
        arguments: event.arguments,
        observedStartAt: at,
      };
      const turn = patchStageIteration(staged.turn, stage, (iteration) => {
        if (iteration.tools.some((item) => item.id === tool.id)) return iteration;
        return {
          ...iteration,
          status: "running",
          startedAt: iteration.startedAt ?? at,
          tools: [...iteration.tools, tool],
        };
      });
      const flatTool: StudyMaterialsToolView = { ...tool, stage };
      return {
        ...staged,
        turn: {
          ...turn,
          tools: patchFlatTool(staged.turn.tools, event.stepId, () => flatTool),
        },
      };
    }

    case "tool_result": {
      const existing = findTool(state.turn, event.stepId);
      const name = event.name ?? existing?.name ?? "";
      const stage = activeStage(state, name);
      const staged = setCurrentStage(state, stage);
      const status: ToolStepStatus = event.success ? "success" : "error";
      const turn = patchStageIteration(staged.turn, stage, (iteration) => {
        const prior = iteration.tools.find((tool) => tool.id === event.stepId);
        const nextTool: ToolStepView = {
          id: event.stepId,
          iteration: (STAGE_INDEX.get(stage) ?? 0) + 1,
          name,
          displayName: event.title ?? prior?.displayName ?? studyToolDisplayName(name),
          ...(prior?.intent ? { intent: prior.intent } : {}),
          status,
          ...(prior?.arguments !== undefined ? { arguments: prior.arguments } : {}),
          result: event.result,
          summary: event.success ? summarizeStudyToolResult(name, event.result) : event.error ?? "执行失败",
          observedStartAt: prior?.observedStartAt ?? at,
          observedResultAt: at,
          ...(event.elapsedMs !== undefined ? { serverDurationMs: event.elapsedMs } : {}),
        };
        const tools = prior
          ? iteration.tools.map((tool) => (tool.id === event.stepId ? nextTool : tool))
          : [...iteration.tools, nextTool];
        return {
          ...iteration,
          tools,
          status: aggregateIterationStatus(tools),
          completedAt: tools.every((tool) => tool.status !== "running" && tool.status !== "queued")
            ? at
            : iteration.completedAt,
        };
      });
      const stages = event.success
        ? staged.stages
        : staged.stages.map((item) =>
            item.id === stage ? { ...item, status: "error" as const } : item,
          );
      const flatTools = patchFlatTool(staged.turn.tools, event.stepId, (prior) => ({
        id: event.stepId,
        iteration: (STAGE_INDEX.get(stage) ?? 0) + 1,
        name,
        displayName: event.title ?? prior?.displayName ?? studyToolDisplayName(name),
        ...(prior?.intent ? { intent: prior.intent } : {}),
        status,
        ...(prior?.arguments !== undefined ? { arguments: prior.arguments } : {}),
        result: event.result,
        summary: event.success ? summarizeStudyToolResult(name, event.result) : event.error ?? "执行失败",
        observedStartAt: prior?.observedStartAt ?? at,
        observedResultAt: at,
        ...(event.elapsedMs !== undefined
          ? { elapsedMs: event.elapsedMs, serverDurationMs: event.elapsedMs }
          : {}),
        stage,
      }));
      return { ...staged, stages, turn: { ...turn, tools: flatTools } };
    }

    case "text_snapshot":
      return {
        ...state,
        markdownSnapshot: event.content,
        turn: { ...state.turn, snapshotMarkdown: event.content },
      };

    case "quality_report":
      return {
        ...state,
        qualityReport: event.report,
        turn: { ...state.turn, qualityReport: event.report },
      };

    case "recovery_available":
      return { ...state, recovery: recoveryFromEvent(event) };

    case "revision_required":
      return { ...state, revisionIssues: event.issues };

    case "subagent_start": {
      const staged = setCurrentStage(state, "research");
      const prior = staged.turn.kpItems.find((item) => item.title === event.knowledgePoint);
      const kpItems = prior
        ? staged.turn.kpItems.map((item) =>
            item.title === event.knowledgePoint ? { ...item, status: "running" as const } : item,
          )
        : [...staged.turn.kpItems, { title: event.knowledgePoint, status: "running" as const }];
      return { ...staged, turn: { ...staged.turn, kpItems } };
    }

    case "subagent_end":
      return {
        ...state,
        turn: {
          ...state.turn,
          kpItems: state.turn.kpItems.map((item) =>
            item.title === event.knowledgePoint ? { ...item, status: "done" } : item,
          ),
        },
      };

    case "done": {
      const material = event.result.material;
      const doneQualityReport = asRecord(event.result.quality_report);
      const markdown = material?.markdown || state.markdownSnapshot;
      const result = markdown && material && !material.markdown
        ? { ...event.result, material: { ...material, markdown } }
        : event.result;
      const normalized = normalizeStudyResult(result);
      return markComplete(
        {
          ...state,
          result,
          qualityReport: doneQualityReport ?? state.qualityReport,
          markdownSnapshot: markdown || state.markdownSnapshot,
          seenTerminal: true,
          progress: 100,
          statusText: "讲义已生成并保存到资料档案",
          turn: {
            ...state.turn,
            result: normalized,
            qualityReport: doneQualityReport ?? state.turn.qualityReport,
            snapshotMarkdown: markdown || state.markdownSnapshot,
            statusText: "讲义已生成并保存到资料档案",
          },
        },
        at,
      );
    }

    case "error": {
      const recovery = event.recoverable === undefined
        ? state.recovery
        : {
            ...(state.recovery ?? { issues: [] }),
            ...(event.stage ? { stage: event.stage } : {}),
            ...(event.code ? { code: event.code } : {}),
            detail: event.message,
            recoverable: event.recoverable,
          };
      const currentStage = event.stage
        ? studyStageFromFailure(event.stage) || state.currentStage
        : state.currentStage;
      return {
        ...state,
        runStatus: "failed",
        seenTerminal: true,
        endedAt: at,
        statusText: event.message,
        ...(recovery ? { recovery } : {}),
        ...(currentStage ? { currentStage } : {}),
        stages: state.stages.map((stage) =>
          stage.id === currentStage ? { ...stage, status: "error" } : stage,
        ),
        turn: {
          ...markActiveTools(state.turn, "error", at),
          runStatus: "error",
          errorMessage: event.message,
        },
      };
    }

    case "ping":
      return state;
  }
}

export function studyMaterialsProjectionReducer(
  state: StudyMaterialsProjection,
  action: StudyMaterialsProjectionAction,
): StudyMaterialsProjection {
  switch (action.type) {
    case "reset":
      return initialStudyMaterialsProjection();

    case "event": {
      const startsNewTask =
        action.event.kind === "task_started" &&
        Boolean(state.taskId) &&
        action.event.taskId !== state.taskId;
      if (!startsNewTask && action.seq && action.seq <= state.lastSeq) return state;
      const base = startsNewTask ? { ...state, lastSeq: 0 } : state;
      const next = applyEvent(base, action.event, action.at);
      return {
        ...next,
        lastSeq: action.seq ? Math.max(next.lastSeq, action.seq) : next.lastSeq,
      };
    }

    case "stop_requested":
      return {
        ...state,
        stopIntent: true,
        statusText: "正在停止接收当前生成…",
      };

    case "settled": {
      if (state.seenTerminal) return state;
      if (action.reason === "error") {
        const message =
          (typeof action.error === "string" ? action.error : action.error?.message) ||
          "连接失败，请稍后继续接收";
        return {
          ...state,
          runStatus: "interrupted",
          endedAt: action.at,
          statusText: message,
          turn: {
            ...markActiveTools(state.turn, "interrupted", action.at),
            runStatus: "interrupted",
            errorMessage: message,
          },
        };
      }
      const reason = action.reason === "aborted" || state.stopIntent ? "已停止接收" : "连接已中断";
      return {
        ...state,
        runStatus: "interrupted",
        endedAt: action.at,
        statusText: `${reason}；服务端任务可能仍在继续`,
        turn: {
          ...markActiveTools(state.turn, "interrupted", action.at),
          runStatus: "interrupted",
        },
      };
    }
  }
}

/** 断点前测试与页面分层使用的简名。 */
export const initialStudyProjection = initialStudyMaterialsProjection;
export const studyProjectionReducer = studyMaterialsProjectionReducer;
export type StudyProjectionState = StudyMaterialsProjection;
