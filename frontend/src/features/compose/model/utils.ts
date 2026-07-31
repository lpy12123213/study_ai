import { ApiError } from "@/shared/api/http-client";
import type { ComposeDraft, ComposeDraftQuestion, SearchQuestion } from "@/shared/api/types";


/** Radix Select 不允许空字符串 value，用哨兵值表示“不限”。 */
export const ANY_VALUE = "__any__";

export function errMsg(err: unknown): string {
  return err instanceof ApiError ? err.message : "网络异常，请稍后重试";
}

/** 组卷网登录态失效的错误码特征（crawler client 经 error 字段透出）。 */
export function isZujuanLoginError(error?: string): boolean {
  const e = String(error ?? "");
  return e.includes("zujuan_cookie") || e.includes("login_required") || e.includes("cookie_expired");
}

export function toInt(v: string, fallback: number): number {
  const n = Number.parseInt(v, 10);
  return Number.isNaN(n) ? fallback : n;
}

/** SearchQuestion.knowledge_points 可能是数组或字符串，统一成字符串。 */
export function knowledgePointsText(q: SearchQuestion): string {
  const kp = q.knowledge_points;
  if (Array.isArray(kp)) return kp.filter(Boolean).join("、");
  return String(kp ?? "");
}

/** 组卷草稿题目 id（camelCase / snake_case 兼容）。 */
export function draftQuestionId(q: ComposeDraftQuestion): string {
  return String(q.questionId ?? q.question_id ?? "").trim();
}

export function verdictVariant(v?: string): "success" | "warning" | "destructive" | "muted" {
  if (v === "好题") return "success";
  if (v === "普通题") return "warning";
  if (v === "差题") return "destructive";
  return "muted";
}

/** 从任务详情（DB 版 / 内存兜底版）中提取组卷草稿。 */
export function extractComposeDraft(detail: unknown): ComposeDraft | null {
  if (!detail || typeof detail !== "object") return null;
  const d = detail as Record<string, any>;
  const fromResult = d.result?.composeDraft;
  if (fromResult && typeof fromResult === "object") return fromResult as ComposeDraft;
  if (d.composeDraft && typeof d.composeDraft === "object") return d.composeDraft as ComposeDraft;
  const events = Array.isArray(d.events) ? (d.events as any[]) : [];
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const data = events[i]?.data;
    const draft = data?.composeDraft ?? data?.compose_draft;
    if (draft && typeof draft === "object") return draft as ComposeDraft;
  }
  return null;
}

