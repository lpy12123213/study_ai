/** 组卷 feature API（compose 流 + 蓝图 + 好题鉴别，自 lib/api/{papers,misc}.ts 迁入，架构 Phase 5）。 */
import { apiFetch } from "@/shared/api/http-client";
import { streamPost, type StreamHandlers } from "@/lib/sse";
import type {
  Blueprint,
  ComposeFilters,
  ComposeOptions,
  ComposeSlot,
  QuestionEvaluateResult,
  SearchQuestion,
} from "@/shared/api/types";

export interface ComposePayload {
  subject: string;
  topic?: string;
  paperName?: string;
  slots: ComposeSlot[];
  filters?: ComposeFilters;
  options?: ComposeOptions;
  taskId?: string;
}

/** 蓝图组卷（POST 即流）。终态 result.result 为 camelCase 试卷；requireHumanReview 时会先收到 pending_review。 */
export function composePaper(payload: ComposePayload, handlers: StreamHandlers) {
  return streamPost("/api/papers/compose", payload, handlers);
}

/** 整卷生成（POST 即流）。 */
export function generateFullPaper(
  payload: { subject: string; topic?: string; paperName?: string; totalPoints?: number; timeLimit?: number; taskId?: string },
  handlers: StreamHandlers,
) {
  return streamPost("/api/papers/generate-full", payload, handlers);
}

export const evaluateApi = {
  search: (payload: {
    query: string;
    subject?: string;
    edu_level?: string;
    difficulty?: string;
    question_type?: string;
    limit?: number;
    max_pages?: number;
    min_quality_score?: number;
  }) =>
    apiFetch<{ success: boolean; query?: string; count?: number; questions?: SearchQuestion[]; error?: string; login_required?: boolean; instructions?: string[] }>(
      "/api/question-evaluate/search",
      { method: "POST", body: payload },
    ),
  evaluate: (payload: { questions: Record<string, any>[]; subject?: string; requirements?: string; model?: string }) =>
    apiFetch<{ results: QuestionEvaluateResult[]; model?: string }>("/api/question-evaluate/evaluate", {
      method: "POST",
      body: payload,
    }),
};

export const blueprintsApi = {
  list: () => apiFetch<Blueprint[]>("/api/blueprints/"),
  get: (id: string) => apiFetch<Blueprint>(`/api/blueprints/${encodeURIComponent(id)}`),
  create: (payload: { name: string; subject: string; topic?: string; slots: { questionType: string; count: number; difficulty?: string }[] }) =>
    apiFetch<Blueprint>("/api/blueprints/", { method: "POST", body: payload }),
  remove: (id: string) => apiFetch(`/api/blueprints/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
