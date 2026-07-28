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
  | { kind: "workflow_stage"; stage: string; lastSuccessfulStage?: string }
  | {
      kind: "tool_call";
      stepId: string;
      name: string;
      title?: string;
      arguments: unknown;
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
    }
  | { kind: "text_snapshot"; content: string }
  | { kind: "quality_report"; report: Record<string, unknown> }
  | { kind: "recovery_available"; recovery: Record<string, unknown> }
  | { kind: "revision_required"; issues: string[]; remainingAttempts?: number }
  | { kind: "subagent_start"; knowledgePoint: string }
  | { kind: "subagent_end"; knowledgePoint: string }
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
      return {
        kind: "workflow_stage",
        stage,
        ...(lastSuccessfulStage ? { lastSuccessfulStage } : {}),
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
      return {
        kind: "tool_call",
        stepId,
        name,
        ...(title ? { title } : {}),
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

    case "subagent_start":
    case "subagent_end": {
      const knowledgePoint = asString(data.knowledge_point) ?? asString(data.title) ?? "";
      if (!knowledgePoint) return null;
      return {
        kind: ev.type === "subagent_start" ? "subagent_start" : "subagent_end",
        knowledgePoint,
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
