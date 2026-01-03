function normalizeBaseUrl(baseUrl: string): string {
  const trimmed = (baseUrl || "").trim();
  if (!trimmed) return "/api";
  return trimmed.replace(/\/+$/, "");
}

export const API_BASE_URL = normalizeBaseUrl(
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api",
);

export function apiUrl(path: string): string {
  const normalizedPath = (path || "").trim().replace(/^\/+/, "");
  return `${API_BASE_URL}/${normalizedPath}`;
}

