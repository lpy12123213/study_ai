/** 题库 feature API（自 lib/api/library.ts 迁入，架构 Phase 5）。
 *  本文件是 question-library 的公共 API 面：跨 feature 只允许从这里导入。 */
import { apiFetch } from "@/shared/api/http-client";
import { streamPost, type StreamHandlers } from "@/lib/sse";
import type { GaokaoQuestionSource, LibraryListResponse, LibraryPreview, LibrarySession } from "@/shared/api/types";

export interface LibraryItemsQuery {
  subject?: string;
  origin?: string;
  area?: "general" | "gaokao" | "all";
  hidden?: "0" | "1" | "all";
  q?: string;
  question_type?: string;
  difficulty?: string;
  year?: string;
  region?: string;
  paper_name?: string;
  question_number?: string;
  only_new?: boolean;
  min_score?: number;
  sort?: "updated_at" | "ai_score";
  order?: "desc" | "asc";
  limit?: number;
  offset?: number;
}

export interface GaokaoQuestionImportItem {
  question_id: string;
  subject: string;
  stem: string;
  answer?: string;
  analysis?: string;
  question_type?: string;
  difficulty?: string;
  difficulty_value?: number | null;
  knowledge_point?: string;
  knowledge_points?: string[];
  origin?: "crawled" | "media";
  source: GaokaoQuestionSource;
}

export const libraryApi = {
  items: (query: LibraryItemsQuery = {}) =>
    apiFetch<LibraryListResponse>("/api/question-library/items", {
      query: { area: "general", hidden: "0", limit: 50, offset: 0, ...query } as any,
    }),
  getItem: (questionId: string) =>
    apiFetch<{ library_item: any; question_cache: any }>(
      `/api/question-library/items/${encodeURIComponent(questionId)}`,
    ),
  hide: (qid: string) => apiFetch(`/api/question-library/items/${encodeURIComponent(qid)}/hide`, { method: "POST" }),
  unhide: (qid: string) => apiFetch(`/api/question-library/items/${encodeURIComponent(qid)}/unhide`, { method: "POST" }),
  star: (qid: string) => apiFetch(`/api/question-library/items/${encodeURIComponent(qid)}/star`, { method: "POST" }),
  unstar: (qid: string) => apiFetch(`/api/question-library/items/${encodeURIComponent(qid)}/unstar`, { method: "POST" }),
  bulkDelete: (questionIds: string[]) =>
    apiFetch<{ success: boolean; deleted: number }>("/api/question-library/items/bulk-delete", {
      method: "POST",
      body: { question_ids: questionIds },
    }),
  exportToBasket: (qid: string) =>
    apiFetch(`/api/question-library/items/${encodeURIComponent(qid)}/export-to-basket`, { method: "POST" }),
  importGaokao: (items: GaokaoQuestionImportItem[]) =>
    apiFetch<{ success: boolean; upserted: number; question_ids: string[] }>(
      "/api/question-library/gaokao/items/manual-import",
      { method: "POST", body: { items } },
    ),

  // ---- 预览审核流 ----
  preview: (previewId: string) =>
    apiFetch<LibraryPreview>(`/api/question-library/previews/${encodeURIComponent(previewId)}`),
  latestPendingPreview: () =>
    apiFetch<{ success: boolean; preview: LibraryPreview | null }>("/api/question-library/previews/latest/pending"),
  commitPreview: (previewId: string, questions: Record<string, any>[]) =>
    apiFetch<{ success: boolean; preview_id: string; inserted: number; question_ids?: string[] }>(
      `/api/question-library/previews/${encodeURIComponent(previewId)}/commit`,
      { method: "POST", body: { questions } },
    ),
  discardPreview: (previewId: string) =>
    apiFetch(`/api/question-library/previews/${encodeURIComponent(previewId)}/discard`, { method: "POST" }),
  regenerateSection: (previewId: string, payload: { question_id: string; section_key: "stem" | "answer" | "analysis" }, handlers: StreamHandlers) =>
    streamPost(`/api/question-library/previews/${encodeURIComponent(previewId)}/regenerate-section`, payload, handlers),

  // ---- 会话 ----
  sessions: () => apiFetch<{ success: boolean; sessions: LibrarySession[] }>("/api/question-library/sessions"),
  session: (sessionId: string) =>
    apiFetch<{ success: boolean; session: any }>(`/api/question-library/sessions/${encodeURIComponent(sessionId)}`),
  stopSession: (sessionId: string) =>
    apiFetch(`/api/question-library/sessions/${encodeURIComponent(sessionId)}/stop`, { method: "POST" }),
  archiveSession: (sessionId: string) =>
    apiFetch(`/api/question-library/sessions/${encodeURIComponent(sessionId)}/archive`, { method: "POST" }),
  reviewQuestion: (sid: string, qid: string) =>
    apiFetch(`/api/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/review`, { method: "POST" }),
  approveQuestion: (sid: string, qid: string) =>
    apiFetch(`/api/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/approve`, { method: "POST" }),
  rejectQuestion: (sid: string, qid: string) =>
    apiFetch(`/api/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/reject`, { method: "POST" }),
  confirmQuestion: (sid: string, qid: string) =>
    apiFetch(`/api/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/confirm`, { method: "POST" }),
  unconfirmQuestion: (sid: string, qid: string) =>
    apiFetch(`/api/question-library/sessions/${encodeURIComponent(sid)}/questions/${encodeURIComponent(qid)}/unconfirm`, { method: "POST" }),
};

export interface LibraryCrawlPayload {
  query: string;
  subject?: string;
  edu_level?: string;
  difficulty?: string;
  question_type?: string;
  limit?: number;
  max_pages?: number;
  min_quality_score?: number;
}

export interface GaokaoQuestionCrawlPayload {
  subject: string;
  query: string;
  edu_level?: string;
  exam_year: number;
  region: string;
  paper_name: string;
  source_contains: string;
  paper_variant?: string;
  source_url?: string;
  source_note?: string;
  verified?: boolean;
  difficulty?: string;
  question_type?: string;
  limit?: number;
  max_pages?: number;
  min_quality_score?: number;
  task_id?: string;
}

export interface LibraryGeneratePayload {
  subject: string;
  topic: string;
  difficulty?: string;
  question_type?: string;
  count?: number;
  use_study_archive?: boolean;
  use_reference_questions?: boolean;
  reference_source?: "any" | "gaokao" | "mock" | "joint";
  reference_year_range?: "all" | "3" | "5";
  mode?: "standard" | "infinite";
  knowledge_points?: string[];
  stream_reasoning?: boolean;
  generation_strategy?: "adaptive_evolution" | "legacy_beam";
  supervision_mode?: "tiered_consensus" | "single";
  policy_mode?: "champion" | "shadow_compare" | "fixed";
  evolution_evaluation?: {
    reference_id?: string;
    solution_fingerprint?: Array<{
      id: string;
      concepts: string[];
      weight?: number;
    }>;
    max_solution_similarity?: number;
  };
  intuition_practice?: {
    practice_goal?: string;
    intuition_kinds?: string[];
    packet_size?: number;
    feedback_mode?: string;
  };
}

/** 题库抓取（POST 即流） */
export function crawlLibrary(payload: LibraryCrawlPayload, handlers: StreamHandlers) {
  return streamPost("/api/question-library/crawl", payload, handlers);
}

/** 高考真题爬取：仅将年份与题源标记匹配的结果写入隔离区。 */
export function crawlGaokaoLibrary(payload: GaokaoQuestionCrawlPayload, handlers: StreamHandlers) {
  return streamPost("/api/question-library/gaokao/crawl", payload, handlers);
}

/** AI 出题（POST 即流）；done 后取 preview_id → libraryApi.preview 进入审核 */
export function generateLibraryQuestions(payload: LibraryGeneratePayload, handlers: StreamHandlers) {
  return streamPost("/api/question-library/generate", payload, handlers);
}

/** AI 评分清洗（POST 即流） */
export function scoreLibrary(payload: { subject: string; limit?: number; batch_size?: number; only_unscored?: boolean }, handlers: StreamHandlers) {
  return streamPost("/api/question-library/score", payload, handlers);
}
