import type { StudyMaterialResult } from "@/shared/api/types";
import type { ConversationTurnView, ToolStepView } from "@/features/chat/model/types";
import type { StudyStageKey } from "./stages";

export type StudyMaterialsRunStatus = "idle" | "running" | "done" | "interrupted" | "failed";

export type StudyMaterialsStageId = "plan" | "research" | "aggregate" | "write" | "review" | "export";

export type StudyMaterialsStageStatus = "pending" | "running" | "success" | "error";

export interface StudyMaterialsStageView {
  id: StudyMaterialsStageId;
  label: string;
  status: StudyMaterialsStageStatus;
  /** 阶段来自工具名推断时为 true；权威 workflow_stage 事件到达后置为 false。 */
  inferred: boolean;
}

export interface StudyMaterialsRecoveryView {
  stage?: string;
  code?: string;
  detail?: string;
  issues: string[];
  recoverable: boolean;
}

/** research_retry_required 事件：检索补充尝试进度。 */
export interface StudyMaterialsResearchRetryView {
  pointIds: string[];
  attempt?: number;
  remainingAttempts?: number;
}

/** continue 前快照的上一版成果，保证改进/加深期间下载入口不丢。 */
export interface StudyMaterialsPreviousResult {
  result: StudyMaterialResult;
  markdownSnapshot: string;
  taskId?: string;
}

/** taskStatus 回填的服务端检索覆盖快照（重连后补齐知识点看板）。 */
export interface StudyMaterialsServerKpCoverage {
  perKpState?: Record<string, unknown>;
  searchSummaryByKp?: Record<string, unknown>;
}

export interface StudyMaterialsToolView extends ToolStepView {
  stage: StudyStageKey;
  /** 后端 tool_result.elapsed_ms；与客户端 observed duration 分开保存。 */
  elapsedMs?: number;
}

export interface StudyMaterialsKnowledgePointView {
  title: string;
  status: "running" | "done" | "error";
  /** 带 subagent_id 的并行子代理才持有；旧事件（仅 knowledge_point）不产出该字段。 */
  subagentId?: string;
  index?: number;
  total?: number;
  /** 子代理类型（knowledge_research / export）。 */
  agentKind?: string;
  /** 子代理内的嵌套工具时间线（按 subagent_id 归因的 tool_call/tool_result）。 */
  steps?: ToolStepView[];
}

export interface NormalizedStudyResult {
  topic?: string;
  subject?: string;
  markdown?: string;
  passed?: boolean;
  issues: string[];
  mdUrl?: string;
  mdFilename?: string;
  texUrl?: string;
  texFilename?: string;
  pdfUrl?: string;
  pdfFilename?: string;
  expiresAt?: string;
  raw: StudyMaterialResult;
}

export interface StudyMaterialsTurnView extends ConversationTurnView {
  tools: StudyMaterialsToolView[];
  kpItems: StudyMaterialsKnowledgePointView[];
  result?: NormalizedStudyResult;
  snapshotMarkdown: string;
  currentStage?: StudyStageKey;
  qualityReport?: Record<string, unknown>;
  statusText: string;
}

export interface StudyMaterialsProjection {
  runStatus: StudyMaterialsRunStatus;
  taskId?: string;
  parentTaskId?: string;
  lastSeq: number;
  statusText: string;
  progress?: number;
  stages: StudyMaterialsStageView[];
  currentStage?: StudyMaterialsStageId;
  turn: StudyMaterialsTurnView;
  /** text_delta 是完整快照；运行中用作草稿预览，完成后与结果对齐。 */
  markdownSnapshot: string;
  /** text_snapshot 到达次数，草稿预览展示「第 N 版草稿」。 */
  snapshotVersion: number;
  result?: StudyMaterialResult;
  qualityReport?: Record<string, unknown>;
  recovery?: StudyMaterialsRecoveryView;
  revisionIssues: string[];
  /** revision_required 携带的剩余修订次数。 */
  remainingRevisionAttempts?: number;
  /** research_retry_required 的最近一次检索补充进度。 */
  researchRetry?: StudyMaterialsResearchRetryView;
  /** probeRecovery 回填的服务端检索覆盖（标注为服务端快照）。 */
  serverKpCoverage?: StudyMaterialsServerKpCoverage;
  /** continue 时保留的上一版成果；新一轮 done 或 reset 时清除。 */
  previousResult?: StudyMaterialsPreviousResult;
  startedAt?: number;
  endedAt?: number;
  seenTerminal: boolean;
  stopIntent: boolean;
  /** 服务端取消已确认（tasksApi.cancel 成功），settled 文案据此区分。 */
  serverCancelConfirmed?: boolean;
}

/** 断点前测试与 selector 使用的名称。 */
export type StudyProjectionState = StudyMaterialsProjection;
