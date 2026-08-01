/**
 * 学习资料流事件的领域契约。
 *
 * 同时兼容：
 * - legacy AgentCore：thinking / step_id / success / output / elapsed_ms；
 * - Codex staged workflow：reasoning_delta / id / is_error / content；
 * - 持久任务信封：taskId / seq / type / data。
 *
 * text_delta 在本领域是完整 Markdown 快照，不是追加增量。
 */
import type { StudyMaterialResult, TaskEvent } from "@/shared/api/types";

export type StudyMaterialsStreamEvent =
  | {
      kind: "task_started";
      taskId: string;
      parentTaskId?: string;
      query?: string;
      subject?: string;
    }
  | { kind: "status"; content: string }
  | { kind: "progress"; percent?: number; stage?: string }
  | { kind: "thinking"; content: string }
  | {
      kind: "workflow_stage";
      stage: string;
      lastSuccessfulStage?: string;
      revisionAttempts?: number;
      researchAttempts?: number;
    }
  | {
      kind: "tool_call";
      stepId: string;
      name: string;
      title?: string;
      arguments: unknown;
      /** 子代理内转发的工具事件：归属子代理（无此字段为主 agent 步骤）。 */
      subagentId?: string;
      /** 冗余知识点名，便于展示与旧逻辑兼容。 */
      knowledgePoint?: string;
    }
  | {
      kind: "tool_result";
      stepId: string;
      name?: string;
      title?: string;
      success: boolean;
      result: unknown;
      error?: string;
      elapsedMs?: number;
      /** 子代理内转发的工具事件：归属子代理（无此字段为主 agent 步骤）。 */
      subagentId?: string;
      /** 冗余知识点名，便于展示与旧逻辑兼容。 */
      knowledgePoint?: string;
    }
  | { kind: "text_snapshot"; content: string }
  | { kind: "quality_report"; report: Record<string, unknown> }
  | { kind: "recovery_available"; recovery: Record<string, unknown> }
  | { kind: "revision_required"; issues: string[]; remainingAttempts?: number }
  | {
      kind: "research_retry_required";
      pointIds: string[];
      attempt?: number;
      remainingAttempts?: number;
    }
  | { kind: "quality_degraded"; issues: string[]; revisionAttempts?: number }
  | {
      kind: "subagent_start";
      knowledgePoint: string;
      /** 稳定子代理 id（sa-{index} 或 sa-export）。 */
      subagentId?: string;
      index?: number;
      total?: number;
      /** 子代理类型（knowledge_research / export）；与事件判别字段区分命名。 */
      agentKind?: string;
    }
  | {
      kind: "subagent_end";
      knowledgePoint: string;
      /** 稳定子代理 id（sa-{index} 或 sa-export）。 */
      subagentId?: string;
      index?: number;
      total?: number;
      /** 子代理类型（knowledge_research / export）；与事件判别字段区分命名。 */
      agentKind?: string;
    }
  | { kind: "done"; result: StudyMaterialResult }
  | {
      kind: "error";
      message: string;
      code?: string;
      stage?: string;
      recoverable?: boolean;
    }
  | { kind: "ping" };

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
}

function parseJsonText(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
}

/** Codex tool_result.content 可能是 JSON 字符串、内容块数组或普通文本。 */
function decodeToolContent(value: unknown): unknown {
  if (typeof value === "string") return parseJsonText(value);
  if (!Array.isArray(value)) return value;

  const text = value
    .map((item) => {
      if (typeof item === "string") return item;
      const record = asRecord(item);
      return asString(record?.text) ?? asString(record?.content) ?? "";
    })
    .filter(Boolean)
    .join("\n");
  return text ? parseJsonText(text) : value;
}

function eventError(data: Record<string, unknown>): string {
  const nested = asRecord(data.error);
  return (
    asString(data.message) ??
    asString(data.error) ??
    asString(nested?.message) ??
    asString(nested?.error) ??
    asString(data.detail) ??
    "生成失败，请稍后重试"
  );
}

/** 把 normalizeEvent 的输出解码成学习资料领域事件；未知事件返回 null。 */
export function decodeStudyMaterialsEvent(ev: TaskEvent): StudyMaterialsStreamEvent | null {
  const data = asRecord(ev.data) ?? {};

  switch (ev.type) {
    case "task_started": {
      const taskId = ev.taskId ?? asString(data.taskId);
      if (!taskId) return null;
      const parentTaskId = asString(data.parentTaskId);
      const query = asString(data.query);
      const subject = asString(data.subject);
      return {
        kind: "task_started",
        taskId,
        ...(parentTaskId ? { parentTaskId } : {}),
        ...(query ? { query } : {}),
        ...(subject ? { subject } : {}),
      };
    }
    // 服务端追赶压缩标记：瞬态/快照历史事件被折叠时给出可见说明。
    case "catch_up": {
      const skipped = typeof data.skipped === "number" ? data.skipped : 0;
      return {
        kind: "status",
        content:
          skipped > 0 ? `已跳过 ${skipped} 条历史过程事件，正在恢复视图…` : "正在恢复视图…",
      };
    }

    case "status":
      return { kind: "status", content: asString(data.content) ?? asString(data.message) ?? "" };

    case "progress": {
      const percent = asNumber(data.percent) ?? asNumber(data.progress) ?? asNumber(data.value);
      const stage = asString(data.stage);
      return {
        kind: "progress",
        ...(percent !== undefined ? { percent } : {}),
        ...(stage ? { stage } : {}),
      };
    }

    case "thinking":
    case "thinking_delta":
    case "reasoning_delta":
      return { kind: "thinking", content: asString(data.content) ?? "" };

    case "workflow_stage": {
      const stage = asString(data.stage);
      if (!stage) return null;
      const lastSuccessfulStage = asString(data.last_successful_stage);
      const revisionAttempts = asNumber(data.revision_attempts);
      const researchAttempts = asNumber(data.research_attempts);
      return {
        kind: "workflow_stage",
        stage,
        ...(lastSuccessfulStage ? { lastSuccessfulStage } : {}),
        ...(revisionAttempts !== undefined ? { revisionAttempts } : {}),
        ...(researchAttempts !== undefined ? { researchAttempts } : {}),
      };
    }

    case "tool_call": {
      const stepId =
        asString(data.step_id) ??
        asString(data.id) ??
        asString(data.tool_use_id) ??
        `tool-${ev.seq || "pending"}`;
      const name = asString(data.name) ?? asString(data.tool) ?? "";
      const title = asString(data.title);
      const subagentId = asString(data.subagent_id);
      const knowledgePoint = asString(data.knowledge_point);
      return {
        kind: "tool_call",
        stepId,
        name,
        ...(title ? { title } : {}),
        ...(subagentId ? { subagentId } : {}),
        ...(knowledgePoint ? { knowledgePoint } : {}),
        arguments: data.arguments ?? data.input ?? {},
      };
    }

    case "tool_result": {
      const stepId =
        asString(data.step_id) ??
        asString(data.id) ??
        asString(data.tool_use_id) ??
        `tool-${ev.seq || "pending"}`;
      const name = asString(data.name) ?? asString(data.tool);
      const title = asString(data.title);
      const subagentId = asString(data.subagent_id);
      const knowledgePoint = asString(data.knowledge_point);
      const explicitSuccess = asBoolean(data.success);
      const isError = asBoolean(data.is_error);
      const success = explicitSuccess ?? !(isError ?? false);
      const error = asString(data.error) ?? asString(asRecord(data.error)?.message);
      const elapsedMs = asNumber(data.elapsed_ms) ?? asNumber(data.duration_ms);
      const result =
        data.output !== undefined
          ? data.output
          : data.result !== undefined
            ? data.result
            : decodeToolContent(data.content);
      return {
        kind: "tool_result",
        stepId,
        ...(name ? { name } : {}),
        ...(title ? { title } : {}),
        ...(subagentId ? { subagentId } : {}),
        ...(knowledgePoint ? { knowledgePoint } : {}),
        success,
        result,
        ...(error ? { error } : {}),
        ...(elapsedMs !== undefined ? { elapsedMs } : {}),
      };
    }

    case "text_delta":
      return { kind: "text_snapshot", content: asString(data.content) ?? "" };

    case "quality_report":
      return { kind: "quality_report", report: data };

    case "recovery_available":
      return { kind: "recovery_available", recovery: data };

    case "revision_required":
      return {
        kind: "revision_required",
        issues: stringList(data.issues),
        ...(asNumber(data.remaining_attempts) !== undefined
          ? { remainingAttempts: asNumber(data.remaining_attempts) }
          : {}),
      };

    case "research_retry_required":
      return {
        kind: "research_retry_required",
        pointIds: stringList(data.point_ids),
        ...(asNumber(data.attempt) !== undefined ? { attempt: asNumber(data.attempt) } : {}),
        ...(asNumber(data.remaining_attempts) !== undefined
          ? { remainingAttempts: asNumber(data.remaining_attempts) }
          : {}),
      };

    case "quality_degraded":
      return {
        kind: "quality_degraded",
        issues: stringList(data.issues),
        ...(asNumber(data.revision_attempts) !== undefined
          ? { revisionAttempts: asNumber(data.revision_attempts) }
          : {}),
      };

    case "subagent_start":
    case "subagent_end": {
      const knowledgePoint = asString(data.knowledge_point) ?? asString(data.title) ?? "";
      if (!knowledgePoint) return null;
      const subagentId = asString(data.subagent_id);
      const index = asNumber(data.index);
      const total = asNumber(data.total);
      const agentKind = asString(data.kind);
      return {
        kind: ev.type === "subagent_start" ? "subagent_start" : "subagent_end",
        knowledgePoint,
        ...(subagentId ? { subagentId } : {}),
        ...(index !== undefined ? { index } : {}),
        ...(total !== undefined ? { total } : {}),
        ...(agentKind ? { agentKind } : {}),
      };
    }

    case "done": {
      const nested = asRecord(data.result);
      return { kind: "done", result: (nested ?? data) as StudyMaterialResult };
    }

    case "error": {
      const code = asString(data.code) ?? asString(asRecord(data.error)?.code);
      const stage = asString(data.stage);
      const recoverable = asBoolean(data.recoverable);
      return {
        kind: "error",
        message: eventError(data),
        ...(code ? { code } : {}),
        ...(stage ? { stage } : {}),
        ...(recoverable !== undefined ? { recoverable } : {}),
      };
    }

    case "ping":
      return { kind: "ping" };

    default:
      return null;
  }
}

/** 断点前测试使用的简名。 */
export const decodeStudyEvent = decodeStudyMaterialsEvent;
