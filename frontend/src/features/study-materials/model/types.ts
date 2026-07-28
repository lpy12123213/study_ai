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
  /** 阶段来自工具名或 workflow_stage 映射，不是后端统一权威状态。 */
  inferred: true;
}

export interface StudyMaterialsRecoveryView {
  stage?: string;
  code?: string;
  detail?: string;
  issues: string[];
  recoverable: boolean;
}

export interface StudyMaterialsToolView extends ToolStepView {
  stage: StudyStageKey;
  /** 后端 tool_result.elapsed_ms；与客户端 observed duration 分开保存。 */
  elapsedMs?: number;
}

export interface StudyMaterialsKnowledgePointView {
  title: string;
  status: "running" | "done" | "error";
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
  /** text_delta 是完整快照；只在完成结果或调试状态使用，不做 legacy 实时预览。 */
  markdownSnapshot: string;
  result?: StudyMaterialResult;
  qualityReport?: Record<string, unknown>;
  recovery?: StudyMaterialsRecoveryView;
  revisionIssues: string[];
  startedAt?: number;
  endedAt?: number;
  seenTerminal: boolean;
  stopIntent: boolean;
}

/** 断点前测试与 selector 使用的名称。 */
export type StudyProjectionState = StudyMaterialsProjection;
