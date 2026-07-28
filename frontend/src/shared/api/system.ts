import { apiFetch } from "@/shared/api/http-client";
import type {
  AppConfig,
  DashboardStats,
  GlobalSearchResult,
  HealthStatus,
  ModelSettings,
} from "@/shared/api/types";

export const systemApi = {
  config: () => apiFetch<AppConfig>("/api/config"),
  health: () => apiFetch<HealthStatus>("/api/health", { silent: true }),
  modelSettings: () => apiFetch<ModelSettings>("/api/model-settings"),
  putModelSettings: (payload: Record<string, any>) =>
    apiFetch<ModelSettings>("/api/model-settings", { method: "PUT", body: payload }),
  fetchModels: (payload: { provider?: string; base_url?: string; api_key?: string }) =>
    apiFetch<{ models: { id: string; owned_by?: string }[]; count: number; url: string }>(
      "/api/model-settings/fetch-models",
      { method: "POST", body: payload },
    ),
  userSettings: () => apiFetch<{ user_id: string; settings: Record<string, any> }>("/api/user-settings"),
  putUserSettings: (settings: Record<string, any>) =>
    apiFetch<{ user_id: string; settings: Record<string, any> }>("/api/user-settings", {
      method: "PUT",
      body: { settings },
    }),
  search: (q: string, types?: string, limit = 30) =>
    apiFetch<{ query: string; results: GlobalSearchResult[]; count: number }>("/api/search", {
      query: { q, types, limit },
    }),
  recordSearchHistory: (search_type: string, search_query: string, result_count: number) =>
    apiFetch("/api/search-history", {
      method: "POST",
      body: { search_type, search_query, result_count },
      silent: true,
    }).catch(() => undefined),
  dashboardStats: (days = 30) => apiFetch<DashboardStats>("/api/dashboard/stats", { query: { days } }),
  llmDebug: (limit = 50) => apiFetch<{ calls: any[]; totals?: any; by_model?: any }>("/api/llm-debug", { query: { limit } }),
};
