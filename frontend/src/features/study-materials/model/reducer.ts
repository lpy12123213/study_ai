import type {
  ToolIterationView,
  ToolStepStatus,
  ToolStepView,
} from "@/features/chat/model/types";
import type { StudyMaterialsStreamEvent } from "../streaming/contract";
import type {
  NormalizedStudyResult,
  StudyMaterialsKnowledgePointView,
  StudyMaterialsPreviousResult,
  StudyMaterialsProjection,
  StudyMaterialsRecoveryView,
  StudyMaterialsStageId,
  StudyMaterialsStageView,
  StudyMaterialsToolView,
  StudyMaterialsTraceEntry,
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
  | { type: "server_cancel_confirmed"; at: number }
  | { type: "begin_continuation" }
  | { type: "restore_previous_result"; at: number }
  | {
      type: "hydrate_server_state";
      perKpState?: Record<string, unknown>;
      searchSummaryByKp?: Record<string, unknown>;
    }
  | { type: "settled"; reason: StudyMaterialsStreamEndReason; at: number; error?: Error | string };

export const STUDY_MATERIALS_STAGES: ReadonlyArray<{
  id: StudyMaterialsStageId;
  label: string;
}> = STUDY_STAGE_ORDER.map((id) => ({ id, label: STUDY_STAGE_LABELS[id] }));

const STAGE_INDEX = new Map(STUDY_MATERIALS_STAGES.map((stage, index) => [stage.id, index]));

/** 单个知识点条目的嵌套 steps 上限：超出丢弃最旧、保留最新（与 tasks store MAX_EVENTS 截尾语义一致）。 */
const MAX_KP_STEPS = 50;

/** 单泳道时间线条目上限：超出丢弃最旧（与 MAX_KP_STEPS 截尾语义一致）。 */
const MAX_TRACE_ENTRIES = 120;

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
    snapshotVersion: 0,
    revisionIssues: [],
    todos: {},
    traceByAgent: {},
    sectionStatus: {},
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
  opts?: { authoritative?: boolean },
): StudyMaterialsProjection {
  const currentIndex = STAGE_INDEX.get(stage) ?? 0;
  const stages = state.stages.map((item, index) => {
    if (item.id === stage) {
      return {
        ...item,
        status: "running" as const,
        // 权威 workflow_stage 到达后摘掉「推断」标注；工具推断保持 inferred。
        ...(opts?.authoritative ? { inferred: false } : {}),
      };
    }
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

type SubagentToolEvent = Extract<StudyMaterialsStreamEvent, { kind: "tool_call" | "tool_result" }>;

/**
 * 子代理内的嵌套工具步骤：镜像扁平 tool_result 构造（displayName/summary/耗时），
 * iteration 无阶段意义，固定为 0（ToolStep 渲染不依赖它）。
 */
function buildKpStep(
  ev: SubagentToolEvent,
  prior: ToolStepView | undefined,
  at: number,
): ToolStepView {
  const name = ev.kind === "tool_result" ? (ev.name ?? prior?.name ?? "") : ev.name;
  const displayName = ev.title ?? prior?.displayName ?? studyToolDisplayName(name);
  if (ev.kind === "tool_call") {
    return {
      id: ev.stepId,
      iteration: 0,
      name,
      displayName,
      intent: studyToolIntent(name, ev.arguments),
      status: "running",
      arguments: ev.arguments,
      observedStartAt: at,
    };
  }
  return {
    id: ev.stepId,
    iteration: 0,
    name,
    displayName,
    ...(prior?.intent ? { intent: prior.intent } : {}),
    status: ev.success ? "success" : "error",
    ...(prior?.arguments !== undefined ? { arguments: prior.arguments } : {}),
    result: ev.result,
    summary: ev.success ? summarizeStudyToolResult(name, ev.result) : ev.error ?? "执行失败",
    observedStartAt: prior?.observedStartAt ?? at,
    observedResultAt: at,
    ...(ev.elapsedMs !== undefined ? { serverDurationMs: ev.elapsedMs } : {}),
  };
}

/** 按 subagent_id 把嵌套工具步骤挂到对应知识点条目（无匹配条目时原样返回）。 */
function patchKpSteps(
  kpItems: StudyMaterialsKnowledgePointView[],
  subagentId: string,
  stepId: string,
  build: (prior: ToolStepView | undefined) => ToolStepView,
): StudyMaterialsKnowledgePointView[] {
  return kpItems.map((item) => {
    if (item.subagentId !== subagentId) return item;
    const prior = item.steps?.find((step) => step.id === stepId);
    const step = build(prior);
    return {
      ...item,
      steps: prior
        ? (item.steps ?? []).map((existing) => (existing.id === stepId ? step : existing))
        : [...(item.steps ?? []).slice(-(MAX_KP_STEPS - 1)), step],
    };
  });
}

/** 子代理条目匹配：优先 subagentId，缺省回退 knowledge_point 标题。 */
function matchKpItem(
  item: StudyMaterialsKnowledgePointView,
  event: Extract<StudyMaterialsStreamEvent, { kind: "subagent_start" | "subagent_end" }>,
): boolean {
  return event.subagentId ? item.subagentId === event.subagentId : item.title === event.knowledgePoint;
}

/** 泳道条目草稿：id/at 由 appendTraceEntry 统一补齐。 */
type TraceEntryDraft =
  | { kind: "thinking"; text: string }
  | { kind: "tool"; tool: ToolStepView }
  | { kind: "note"; name: string; chars: number }
  | { kind: "figure"; figureId: string; stage: string; status?: string }
  | { kind: "section"; secId: string; status: string };

/** 时间线条目 id：优先事件 seq（单调递增），缺省回退时间戳 + 泳道长度。 */
function traceEntryId(agentPath: string, at: number, seq: number | undefined, laneLength: number): string {
  return seq !== undefined ? `${agentPath}:s${seq}` : `${agentPath}:t${at}-${laneLength}`;
}

/** 向指定泳道追加条目（超出上限丢弃最旧）；其它泳道引用保持不变。 */
function appendTraceEntry(
  traceByAgent: Record<string, StudyMaterialsTraceEntry[]>,
  agentPath: string,
  draft: TraceEntryDraft,
  at: number,
  seq: number | undefined,
): Record<string, StudyMaterialsTraceEntry[]> {
  const lane = traceByAgent[agentPath] ?? [];
  const entry: StudyMaterialsTraceEntry = {
    ...draft,
    id: traceEntryId(agentPath, at, seq, lane.length),
    at,
  };
  return { ...traceByAgent, [agentPath]: [...lane.slice(-(MAX_TRACE_ENTRIES - 1)), entry] };
}

/** 相邻 thinking_delta 合并为一个思考块，避免高频增量撑爆泳道。 */
function appendThinkingEntry(
  traceByAgent: Record<string, StudyMaterialsTraceEntry[]>,
  agentPath: string,
  text: string,
  at: number,
  seq: number | undefined,
): Record<string, StudyMaterialsTraceEntry[]> {
  const lane = traceByAgent[agentPath] ?? [];
  const last = lane[lane.length - 1];
  if (last?.kind === "thinking") {
    const merged: StudyMaterialsTraceEntry = { ...last, text: last.text + text };
    return { ...traceByAgent, [agentPath]: [...lane.slice(0, -1), merged] };
  }
  return appendTraceEntry(traceByAgent, agentPath, { kind: "thinking", text }, at, seq);
}

/** 泳道内工具卡片：tool_call 新建，tool_result 按 stepId 覆盖（镜像 buildKpStep 的扁平构造）。 */
function patchTraceTool(
  traceByAgent: Record<string, StudyMaterialsTraceEntry[]>,
  agentPath: string,
  event: SubagentToolEvent,
  at: number,
  seq: number | undefined,
): Record<string, StudyMaterialsTraceEntry[]> {
  const lane = traceByAgent[agentPath] ?? [];
  const index = lane.findIndex((entry) => entry.kind === "tool" && entry.tool.id === event.stepId);
  if (index >= 0) {
    const prior = lane[index];
    if (prior.kind !== "tool") return traceByAgent;
    const next: StudyMaterialsTraceEntry = { ...prior, tool: buildKpStep(event, prior.tool, at) };
    return {
      ...traceByAgent,
      [agentPath]: lane.map((entry, entryIndex) => (entryIndex === index ? next : entry)),
    };
  }
  return appendTraceEntry(
    traceByAgent,
    agentPath,
    { kind: "tool", tool: buildKpStep(event, undefined, at) },
    at,
    seq,
  );
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
    kpItems: turn.kpItems.map((item) =>
      item.steps && item.steps.length > 0
        ? {
            ...item,
            steps: item.steps.map((step) =>
              step.status === "running" || step.status === "queued"
                ? { ...step, status, observedResultAt: step.observedResultAt ?? at }
                : step,
            ),
          }
        : item,
    ),
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
    kpItems: state.turn.kpItems.map((item) =>
      item.steps && item.steps.length > 0
        ? {
            ...item,
            steps: item.steps.map((step) =>
              step.status === "running" || step.status === "queued"
                ? { ...step, status: "success", observedResultAt: step.observedResultAt ?? at }
                : step,
            ),
          }
        : item,
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

/** continue 前把当前成果快照为「上一版」，没有结果时不产生快照。 */
function snapshotPreviousResult(
  state: StudyMaterialsProjection,
): StudyMaterialsPreviousResult | undefined {
  if (!state.result) return undefined;
  return {
    result: state.result,
    markdownSnapshot: state.markdownSnapshot,
    ...(state.taskId ? { taskId: state.taskId } : {}),
  };
}

function applyEvent(
  state: StudyMaterialsProjection,
  event: StudyMaterialsStreamEvent,
  at: number,
  seq?: number,
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
          serverCancelConfirmed: false,
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
      return stage ? setCurrentStage(state, stage, { authoritative: true }) : state;
    }

    case "thinking_delta": {
      if (!event.text) return state;
      return {
        ...state,
        runStatus: "running",
        startedAt: state.startedAt ?? at,
        traceByAgent: appendThinkingEntry(state.traceByAgent, event.agentPath, event.text, at, seq),
      };
    }

    case "note_write":
      return {
        ...state,
        traceByAgent: appendTraceEntry(
          state.traceByAgent,
          event.agentPath,
          { kind: "note", name: event.name, chars: event.chars },
          at,
          seq,
        ),
      };

    case "todo_update":
      // 同 id 覆盖；Record 键序保持首次出现顺序，清单展示稳定。
      return { ...state, todos: { ...state.todos, [event.todo.id]: event.todo } };

    case "figure_trace":
      return {
        ...state,
        traceByAgent: appendTraceEntry(
          state.traceByAgent,
          event.agentPath,
          {
            kind: "figure",
            figureId: event.figureId,
            stage: event.stage,
          },
          at,
          seq,
        ),
      };

    case "section_fill":
      return {
        ...state,
        sectionStatus: { ...state.sectionStatus, [event.secId]: event.status },
        traceByAgent: appendTraceEntry(
          state.traceByAgent,
          event.agentPath,
          { kind: "section", secId: event.secId, status: event.status },
          at,
          seq,
        ),
      };

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
      const kpItems = event.subagentId
        ? patchKpSteps(staged.turn.kpItems, event.subagentId, event.stepId, (prior) =>
            buildKpStep(event, prior, at),
          )
        : staged.turn.kpItems;
      // 带 agent_path 的工具事件同步进过程泳道；旧事件（无 agentPath）不动泳道。
      const traceByAgent = event.agentPath
        ? patchTraceTool(staged.traceByAgent, event.agentPath, event, at, seq)
        : staged.traceByAgent;
      return {
        ...staged,
        traceByAgent,
        turn: {
          ...turn,
          kpItems,
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
      const kpItems = event.subagentId
        ? patchKpSteps(staged.turn.kpItems, event.subagentId, event.stepId, (prior) =>
            buildKpStep(event, prior, at),
          )
        : staged.turn.kpItems;
      // 带 agent_path 的工具事件同步进过程泳道；旧事件（无 agentPath）不动泳道。
      const traceByAgent = event.agentPath
        ? patchTraceTool(staged.traceByAgent, event.agentPath, event, at, seq)
        : staged.traceByAgent;
      return { ...staged, stages, traceByAgent, turn: { ...turn, kpItems, tools: flatTools } };
    }

    case "text_snapshot":
      return {
        ...state,
        markdownSnapshot: event.content,
        snapshotVersion: state.snapshotVersion + 1,
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
      return {
        ...state,
        revisionIssues: event.issues,
        ...(event.remainingAttempts !== undefined
          ? { remainingRevisionAttempts: event.remainingAttempts }
          : {}),
      };

    case "research_retry_required":
      return {
        ...state,
        researchRetry: {
          pointIds: event.pointIds,
          ...(event.attempt !== undefined ? { attempt: event.attempt } : {}),
          ...(event.remainingAttempts !== undefined
            ? { remainingAttempts: event.remainingAttempts }
            : {}),
        },
      };

    case "quality_degraded":
      // 质量降级不重写 remainingRevisionAttempts（事件携带的是已用次数）。
      return { ...state, revisionIssues: event.issues };

    case "subagent_start": {
      const staged = setCurrentStage(state, "research");
      const prior = staged.turn.kpItems.find((item) => matchKpItem(item, event));
      if (prior) {
        // 同一 kp/subagentId 再次 start（重规划/多 foreach 块复用 id）视为新一轮：清空嵌套 steps、状态归 running。
        const kpItems = staged.turn.kpItems.map((item) =>
          matchKpItem(item, event)
            ? { ...item, status: "running" as const, ...(item.steps ? { steps: [] } : {}) }
            : item,
        );
        return { ...staged, turn: { ...staged.turn, kpItems } };
      }
      const item: StudyMaterialsKnowledgePointView = {
        title: event.knowledgePoint,
        status: "running",
        ...(event.subagentId ? { subagentId: event.subagentId } : {}),
        ...(event.index !== undefined ? { index: event.index } : {}),
        ...(event.total !== undefined ? { total: event.total } : {}),
        ...(event.agentKind ? { agentKind: event.agentKind } : {}),
        // 嵌套工具时间线仅在带 subagent_id 的（并行）子代理上建立。
        ...(event.subagentId ? { steps: [] } : {}),
      };
      return { ...staged, turn: { ...staged.turn, kpItems: [...staged.turn.kpItems, item] } };
    }

    case "subagent_end":
      return {
        ...state,
        turn: {
          ...state.turn,
          kpItems: state.turn.kpItems.map((item) =>
            matchKpItem(item, event) ? { ...item, status: "done" } : item,
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
          // 新一轮完成：上一版快照与检索重试进度不再需要保留。
          previousResult: undefined,
          researchRetry: undefined,
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
      const next = applyEvent(base, action.event, action.at, action.seq);
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

    case "server_cancel_confirmed":
      if (!state.stopIntent) return state;
      return { ...state, serverCancelConfirmed: true };

    case "begin_continuation": {
      const previousResult = snapshotPreviousResult(state);
      return {
        ...initialStudyMaterialsProjection(),
        ...(previousResult ? { previousResult } : {}),
      };
    }

    case "restore_previous_result": {
      const previous = state.previousResult;
      if (!previous) return state;
      return {
        ...state,
        runStatus: "done",
        result: previous.result,
        markdownSnapshot: previous.markdownSnapshot,
        ...(previous.taskId ? { taskId: previous.taskId } : {}),
        statusText: "已还原上一版成果",
        endedAt: action.at,
        previousResult: undefined,
        recovery: undefined,
        turn: {
          ...state.turn,
          runStatus: "done",
          errorMessage: undefined,
          result: normalizeStudyResult(previous.result),
          snapshotMarkdown: previous.markdownSnapshot,
          statusText: "已还原上一版成果",
        },
      };
    }

    case "hydrate_server_state": {
      const perKpState = asRecord(action.perKpState);
      const searchSummaryByKp = asRecord(action.searchSummaryByKp);
      if (!perKpState && !searchSummaryByKp) return state;
      return {
        ...state,
        serverKpCoverage: {
          ...(perKpState ? { perKpState } : {}),
          ...(searchSummaryByKp ? { searchSummaryByKp } : {}),
        },
      };
    }

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
      const stopped = action.reason === "aborted" || state.stopIntent;
      // 服务端取消已确认时不声称任务仍在继续；否则保持诚实提示。
      const statusText = stopped
        ? state.serverCancelConfirmed
          ? "已停止，服务端任务已取消"
          : "已停止接收；服务端任务可能仍在继续"
        : "连接已中断；服务端任务可能仍在继续";
      return {
        ...state,
        runStatus: "interrupted",
        endedAt: action.at,
        statusText,
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
