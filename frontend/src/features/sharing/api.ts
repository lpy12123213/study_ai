/** 分享 feature API（自 lib/api/misc.ts 迁入，架构 Phase 5）。 */
import { apiFetch } from "@/shared/api/http-client";
import type { ShareMeta } from "@/shared/api/types";

export const shareApi = {
  createLink: (payload: { item_type: "paper" | "study_archive" | "template"; item_id: string; expires_in_s?: number; password?: string }) =>
    apiFetch<{ success: boolean; token: string; item_type: string; expires_at?: string | null; has_password?: boolean }>(
      "/api/share-links",
      { method: "POST", body: payload },
    ),
  meta: (token: string) => apiFetch<ShareMeta>(`/api/share/${encodeURIComponent(token)}`, { silent: true }),
  validate: (token: string, password?: string) =>
    apiFetch<ShareMeta>(`/api/share/${encodeURIComponent(token)}/validate`, {
      method: "POST",
      body: { password: password ?? "" },
      silent: true,
    }),
  content: (token: string, password?: string) =>
    apiFetch<{ success: boolean; item_type: string; paper?: any; study_archive?: any; template?: any }>(
      `/api/share/${encodeURIComponent(token)}/content`,
      { method: "POST", body: { password: password ?? "" }, silent: true },
    ),
};
