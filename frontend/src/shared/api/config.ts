/**
 * 统一 API origin 配置（架构 Phase 1：shared 层，F2）。
 *
 * 后端路径约定已包含 /api 前缀（如 "/api/conversations"），因此本模块产出的
 * 是“前缀”：默认空串（同源反代，与既有行为逐字节一致）；部署配置了
 * VITE_API_BASE_URL 时才把该 origin 前置到 /api 路径之前。
 *
 * 本模块不导入 React / Zustand / 任何业务模块（与 http-client.ts 同级）。
 */

/** 读取并规范化 VITE_API_BASE_URL，返回要前置到 /api 路径之前的 origin 前缀。 */
export function resolveApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL;
  if (!raw) return "";
  let value = String(raw).trim();
  if (!value) return "";
  // 去掉结尾的 "/" 与多余的 "/api" 后缀（如 "https://api.example.com/api/" → "https://api.example.com"）
  value = value.replace(/\/+$/, "");
  value = value.replace(/\/api$/i, "");
  value = value.replace(/\/+$/, "");
  return value;
}

/** 是否为跨域部署：base 为绝对 origin（http(s):// 或协议相对 //）。 */
export function isCrossOrigin(): boolean {
  return /^([a-z][a-z\d+.-]*:)?\/\//i.test(resolveApiBaseUrl());
}

/** 凭证策略：跨域必须 include（携带 cookie），同源保持 same-origin。 */
export function resolveCredentials(): RequestCredentials {
  return isCrossOrigin() ? "include" : "same-origin";
}

/**
 * 把 base 前缀拼到已含 /api 的 path 之前。
 * - base 默认取 resolveApiBaseUrl()（同源默认空串 → 原样返回 path）。
 * - 防双 /api：base 以 /api 结尾且 path 以 /api 开头时，去掉 path 的 /api 前缀。
 * - 防双 //：base 去掉结尾 "/" 后再拼接。
 */
export function joinApiUrl(path: string, base: string = resolveApiBaseUrl()): string {
  const prefix = (base ?? "").trim().replace(/\/+$/, "");
  let rest = path.startsWith("/") ? path : `/${path}`;
  if (prefix && /\/api$/i.test(prefix) && /^\/api/i.test(rest)) {
    rest = rest.replace(/^\/api/i, "");
  }
  return `${prefix}${rest}`;
}

/** EventSource 专用：joinApiUrl + URLSearchParams 查询串（query 可选）。 */
export function buildEventSourceUrl(
  path: string,
  query?: Record<string, string | number | boolean | undefined | null>,
  base: string = resolveApiBaseUrl(),
): string {
  const joined = joinApiUrl(path, base);
  if (!query) return joined;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue;
    params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${joined}?${qs}` : joined;
}
