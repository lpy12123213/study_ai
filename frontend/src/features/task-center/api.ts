/** 任务中心 feature API（自 lib/api/tasks.ts 迁入，架构 Phase 5）。
 *  tasksApi 亦被 Task Coordinator 注入为 REST 校准源（stores/tasks.ts）。 */
import { apiFetch } from "@/shared/api/http-client";
import type { ExportFileInfo, TaskSummary } from "@/shared/api/types";

export interface TaskDetail extends TaskSummary {
  request?: any;
  result?: any;
  error?: any;
  events?: any[];
  // 内存兜底版字段
  taskId?: string;
  type?: string;
  steps?: any[];
  first_seq?: number;
}

export const tasksApi = {
  list: (opts?: { status?: string; type?: string; limit?: number; offset?: number }) =>
    apiFetch<{ tasks: TaskSummary[]; count: number }>("/api/tasks", {
      query: { status: opts?.status, type: opts?.type, limit: opts?.limit ?? 50, offset: opts?.offset ?? 0 },
    }),
  get: (taskId: string, opts?: { includeEvents?: boolean; eventsLimit?: number; eventsAfterSeq?: number }) =>
    apiFetch<TaskDetail>(`/api/tasks/${encodeURIComponent(taskId)}`, {
      query: {
        include_events: opts?.includeEvents ?? false,
        events_limit: opts?.eventsLimit,
        events_after_seq: opts?.eventsAfterSeq,
      },
    }),
  pause: (taskId: string) => apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/pause`, { method: "POST" }),
  resume: (taskId: string) => apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/resume`, { method: "POST" }),
  cancel: (taskId: string) => apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" }),
  retry: (taskId: string) =>
    apiFetch<{ success: boolean; taskId: string }>(`/api/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST" }),
  /** 组卷人工审核提交。questions 每项至少含 questionId；剔除用 reviewAction: "reject"。 */
  composeReview: (taskId: string, payload: { questions: Record<string, any>[]; paperName?: string; paperId?: number }) =>
    apiFetch<{ success: boolean; taskId: string; paper?: any; review?: { approved: number; rejected: number } }>(
      `/api/tasks/${encodeURIComponent(taskId)}/compose-review`,
      { method: "POST", body: payload },
    ),
};

export const exportsApi = {
  files: (opts?: { type?: string; limit?: number; offset?: number }) =>
    apiFetch<{ files: ExportFileInfo[]; count: number }>("/api/exports/files", {
      query: { type: opts?.type, limit: opts?.limit ?? 50, offset: opts?.offset ?? 0 },
    }),
  zip: (filenames: string[]) =>
    apiFetch<{ success: boolean; url: string; filename: string; bytes: number; expires_at?: string }>(
      "/api/exports/zip",
      { method: "POST", body: { filenames } },
    ),
};
