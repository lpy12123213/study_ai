/** 学习资料 feature API（自 lib/api/materials.ts 迁入，架构 Phase 5）。 */
import { apiFetch } from "@/shared/api/http-client";
import { streamGet, streamPost, type StreamHandlers } from "@/lib/sse";
import type { StudyArchive, StudyArchiveSummary, StudyPreset, TaskEvent } from "@/shared/api/types";

/** 档案列表项：base_fingerprint 已在后端行序列化中下发，但共享类型尚未声明。 */
export type StudyArchiveSummaryItem = StudyArchiveSummary & { base_fingerprint?: string };

export interface StudyGeneratePayload {
  query: string;
  subject?: string;
  preset?: StudyPreset | "";
  requirements?: string;
  with_questions?: boolean;
  with_diagrams?: boolean;
  enable_extra_tools?: boolean;
  max_points?: number;
  prefer_local_archive?: boolean;
}

/** 生成学习资料（POST 即流）。工作流事件：workflow_stage / thinking / tool_call / tool_result / text_delta / quality_report / done。 */
export function generateStudyMaterials(payload: StudyGeneratePayload, handlers: StreamHandlers) {
  return streamPost("/api/study-materials/generate", payload, handlers);
}

export interface StudyTaskStatus {
  task_id: string;
  query?: string;
  status?: string;
  error?: string | null;
  resumable?: boolean;
  recovery_available?: boolean;
  last_success_step?: string;
  last_failed_step?: string;
  last_success_stage?: string;
  last_failed_stage?: string;
  first_seq?: number;
  last_seq?: number;
  per_kp_state?: Record<string, unknown>;
  search_summary_by_kp?: Record<string, unknown>;
}

/** GET /tasks/{id}/trace 的一页全量过程事件（备用；过程面板当前走 SSE 流，不依赖该端点）。 */
export interface StudyTaskTracePage {
  events: TaskEvent[];
  next_after_seq: number;
  has_more: boolean;
}

export const studyMaterialsApi = {
  taskStatus: (taskId: string) =>
    apiFetch<StudyTaskStatus>(`/api/study-materials/tasks/${encodeURIComponent(taskId)}`),
  continueTask: (taskId: string, mode: string, handlers: StreamHandlers) =>
    streamPost(`/api/study-materials/tasks/${encodeURIComponent(taskId)}/continue`, { mode }, handlers),
  resumeTask: (taskId: string, afterSeq: number, handlers: StreamHandlers) =>
    streamGet(
      `/api/study-materials/tasks/${encodeURIComponent(taskId)}/stream?after_seq=${Math.max(0, afterSeq)}`,
      handlers,
    ),
  /** 全量过程事件分页（trace 面板/调试备用，UI 尚未接入）。 */
  traceEvents: (taskId: string, opts?: { afterSeq?: number; limit?: number }) =>
    apiFetch<StudyTaskTracePage>(`/api/study-materials/tasks/${encodeURIComponent(taskId)}/trace`, {
      query: { after_seq: opts?.afterSeq ?? 0, limit: opts?.limit ?? 500 },
    }),
  convertToLatex: (payload: { markdown: string; topic?: string; subject?: string }) =>
    apiFetch<{ tex_url: string; filename: string; sha256?: string; bytes?: number; model?: string }>(
      "/api/study-materials/convert-markdown-to-latex",
      { method: "POST", body: payload },
    ),
};

export const studyArchivesApi = {
  list: (opts?: { limit?: number; offset?: number }) =>
    apiFetch<{ items: StudyArchiveSummaryItem[]; count: number }>("/api/study-archives", {
      query: { limit: opts?.limit ?? 50, offset: opts?.offset ?? 0 },
    }),
  /**
   * 按 base_fingerprint 列出版本历史。
   * 服务端过滤为后续波段契约；当前先行客户端过滤兜底（items 已带 base_fingerprint）。
   */
  listByBaseFingerprint: async (baseFingerprint: string, opts?: { limit?: number }) => {
    const fp = baseFingerprint.trim();
    const res = await apiFetch<{ items: StudyArchiveSummaryItem[]; count: number }>(
      "/api/study-archives",
      { query: { base_fingerprint: fp, limit: opts?.limit ?? 50, offset: 0 } },
    );
    const items = res.items.filter((item) => !item.base_fingerprint || item.base_fingerprint === fp);
    return { items, count: items.length };
  },
  get: (id: number) => apiFetch<StudyArchive>(`/api/study-archives/${id}`),
  create: (payload: { subject: string; topic: string; preset?: string; requirements?: string; markdown: string; sections?: Record<string, unknown>[] }) =>
    apiFetch<{ success: boolean; archive: StudyArchive }>("/api/study-archives", { method: "POST", body: payload }),
  clone: (id: number, payload?: { topic?: string; preset?: string; requirements?: string }) =>
    apiFetch<{ success: boolean; archive: StudyArchive }>(`/api/study-archives/${id}/clone`, {
      method: "POST",
      body: payload ?? {},
    }),
};
