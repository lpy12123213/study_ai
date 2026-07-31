import { ApiError } from "@/shared/api/http-client";


// ---------------- 常量 ----------------

export const PAGE_SIZE = 20;

export const ORIGIN_LABELS: Record<string, string> = {
  crawled: "抓取",
  ai: "AI 生成",
  media: "媒体录入",
};

/** AI 出题 11 阶段（与 backend/generation/question_library/stages.py 对齐） */
export const GENERATION_STAGES = [
  { id: "source_pack", label: "素材整理", order: 1 },
  { id: "curriculum_context", label: "课标对齐", order: 2 },
  { id: "reference_crawl", label: "参考题爬取", order: 3 },
  { id: "reference_analysis", label: "参考题分析", order: 4 },
  { id: "brainstorm", label: "直觉原子设计", order: 5 },
  { id: "spec_search", label: "练习包设计", order: 6 },
  { id: "draft_realization", label: "练习包生成", order: 7 },
  { id: "diagram_generation", label: "配图生成", order: 8 },
  { id: "judge", label: "快速校验", order: 9 },
  { id: "final_selection", label: "练习包去重", order: 10 },
  { id: "pending_review", label: "待审核预览", order: 11 },
] as const;

export type SectionKey = "stem" | "answer" | "analysis";

// ---------------- 工具函数 ----------------

export function apiErrorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

export function parseKnowledgePoints(raw: string): string[] {
  return raw
    .split(/[,，、;；\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 20);
}

export function verdictVariant(verdict?: string): "success" | "warning" | "destructive" | "muted" {
  if (!verdict) return "muted";
  if (verdict.includes("好")) return "success";
  if (verdict.includes("差")) return "destructive";
  if (verdict.includes("普通")) return "warning";
  return "muted";
}

