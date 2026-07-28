/**
 * 纯 HTTP client（架构 Phase 1：shared 层）。
 *
 * 不导入 React / Zustand / 任何业务模块。所有横切副作用（鉴权头、限流提示、
 * 组卷网登录态检查）通过 configureHttpClient 注入，由 app 层 observers 接线。
 * 见 src/app/api/http-observers.ts。
 */

/** 规范化后的 API 错误。后端错误载荷同时含 code / detail / error.code，这里统一收敛。 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId?: string;
  readonly details?: unknown;

  constructor(init: { code: string; message: string; status: number; requestId?: string; details?: unknown }) {
    super(init.message);
    this.name = "ApiError";
    this.code = init.code;
    this.status = init.status;
    this.requestId = init.requestId;
    this.details = init.details;
  }

  get isRateLimited() {
    return this.status === 429;
  }
}

export type QueryParams = Record<string, string | number | boolean | undefined | null>;

export interface ApiFetchOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: QueryParams;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** 跳过 429 全局提示（页面自行处理时） */
  silent?: boolean;
}

/** 纯 client 的横切注入点。全部可选；未配置时等价于无鉴权、无观察者。 */
export interface HttpClientOptions {
  /** URL 前缀（默认同源相对路径）。 */
  baseUrl?: string;
  /** 调用时读取访问令牌；返回 null 则不附加 Authorization 头。 */
  getAccessToken?: () => string | null;
  /** 观察任意 JSON 响应载荷（成功与失败均触发）。 */
  onPayload?: (payload: unknown) => void;
  /** 观察规范化后的错误，在抛出之前调用；silent 为调用方传入的静默标记。 */
  onError?: (error: ApiError, context: { silent: boolean }) => void;
}

let options: HttpClientOptions = {};

/** 由 app 层在启动时调用一次（见 app/api/http-observers.ts）。 */
export function configureHttpClient(next: HttpClientOptions): void {
  options = next;
}

/** 测试辅助：清空注入配置。 */
export function resetHttpClient(): void {
  options = {};
}

const SAFE_CODE_RE = /^[a-z0-9_]{1,80}$/;

export function buildQuery(query?: QueryParams): string {
  if (!query) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export function authHeaders(): Record<string, string> {
  const token = options.getAccessToken?.() ?? null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function extractErrorPayload(payload: any, status: number): ApiError {
  const detail = payload?.detail;
  const envelope = payload?.error;
  let code =
    (typeof payload?.code === "string" && payload.code) ||
    (typeof envelope?.code === "string" && envelope.code) ||
    "";
  if (!code && typeof detail === "string") {
    const d = detail.trim();
    code = SAFE_CODE_RE.test(d) ? d : `http_${status}`;
  }
  if (!code) code = `http_${status}`;
  const message =
    (typeof payload?.message === "string" && payload.message) ||
    (typeof envelope?.message === "string" && envelope.message) ||
    (typeof detail === "string" && detail) ||
    code;
  const requestId =
    (typeof payload?.request_id === "string" && payload.request_id) ||
    (typeof envelope?.request_id === "string" && envelope.request_id) ||
    undefined;
  return new ApiError({ code, message, status, requestId, details: detail ?? payload });
}

function notifyPayload(payload: unknown) {
  try {
    options.onPayload?.(payload);
  } catch {
    // 观察者异常不应阻断请求链路
  }
}

function notifyError(error: ApiError, silent: boolean) {
  try {
    options.onError?.(error, { silent });
  } catch {
    // 观察者异常不应掩盖原始错误
  }
}

export async function apiFetch<T = any>(path: string, fetchOptions: ApiFetchOptions = {}): Promise<T> {
  const { method = "GET", body, query, headers, signal, silent } = fetchOptions;
  const url = `${options.baseUrl ?? ""}${path}${buildQuery(query)}`;

  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const finalHeaders: Record<string, string> = {
    ...authHeaders(),
    ...(isForm ? {} : body !== undefined ? { "Content-Type": "application/json" } : {}),
    ...headers,
  };

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers: finalHeaders,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
      signal,
      credentials: "same-origin",
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError({ code: "network_error", message: "网络连接失败，请检查后端服务", status: 0 });
  }

  const contentType = res.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");

  if (!res.ok) {
    let payload: any = null;
    if (isJson) {
      payload = await res.json().catch(() => null);
    }
    notifyPayload(payload);
    const err = extractErrorPayload(payload ?? {}, res.status);
    notifyError(err, silent === true);
    throw err;
  }

  if (!isJson) {
    return (await res.text()) as unknown as T;
  }
  const payload = (await res.json()) as T;
  notifyPayload(payload);
  return payload;
}

/** 把后端相对下载地址（/api/media/generated/...）转为可点击的完整路径。 */
export function downloadUrl(url?: string | null): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("/")) return url;
  return `/api/media/generated/${url}`;
}
