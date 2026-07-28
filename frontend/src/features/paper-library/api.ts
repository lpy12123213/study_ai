/** 试卷库 feature API（papersApi 自 lib/api/papers.ts 迁入，架构 Phase 5）。 */
import { apiFetch } from "@/shared/api/http-client";
import type { ExportResult, PaperDetail, PaperSummary } from "@/shared/api/types";

export const papersApi = {
  list: (limit = 50) => apiFetch<PaperSummary[]>("/api/papers", { query: { limit } }),
  get: (paperId: number, includeAnalysis = false) =>
    apiFetch<PaperDetail>(`/api/papers/${paperId}`, { query: { include_analysis: includeAnalysis } }),
  create: (payload: {
    paper_name: string;
    questions?: { question_id: string; type?: string; difficulty?: string; knowledge_point?: string; source_url?: string }[];
    question_ids?: string[];
  }) => apiFetch<{ success: boolean; paper_id: number; source_mode?: string; message?: string }>("/api/papers", { method: "POST", body: payload }),
  remove: (paperId: number) => apiFetch(`/api/papers/${paperId}`, { method: "DELETE" }),
  export: (
    paperId: number,
    opts: {
      format: "markdown" | "latex" | "pdf" | "docx";
      includeStem?: boolean;
      includeAnswer?: boolean;
      includeAnalysis?: boolean;
      splitBundle?: boolean;
    },
  ) => apiFetch<ExportResult>(`/api/papers/${paperId}/export`, { method: "POST", body: opts }),
  downloadLink: (paperId: number) =>
    apiFetch<{ success: boolean; paper_name?: string; question_count?: number; question_ids?: string[]; question_links?: string[]; instructions?: string[] }>(
      `/api/papers/${paperId}/download-link`,
    ),
};
