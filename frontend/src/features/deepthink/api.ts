/** DeepThink feature API（自 lib/api/misc.ts 迁入，架构 Phase 5）。 */
import { apiFetch } from "@/shared/api/http-client";
import { streamPost, type StreamHandlers } from "@/lib/sse";

export interface DeepThinkPayload {
  question: string;
  subject?: string;
  image_url?: string;
}

/** Canonical 长任务提交：POST /api/tasks/deepthink 创建 RuntimeTask，返回 taskId 供续播/取消。 */
export function submitDeepThink(
  payload: DeepThinkPayload,
  opts?: { signal?: AbortSignal },
): Promise<{ success: boolean; taskId: string }> {
  return apiFetch("/api/tasks/deepthink", { method: "POST", body: payload, signal: opts?.signal });
}

/**
 * 旧版兼容入口（POST 即流，见 backend/api/deepthink.py）。
 * 新页面改用 submitDeepThink + Task Coordinator 续播；此处保留给其他调用方。
 */
export function solveDeepThink(payload: DeepThinkPayload, handlers: StreamHandlers) {
  return streamPost("/api/deepthink", payload, handlers);
}
