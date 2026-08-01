import { ApiError, authHeaders } from "@/shared/api/http-client";
import { buildEventSourceUrl, joinApiUrl, resolveCredentials } from "@/shared/api/config";
import type { TaskEvent } from "@/shared/api/types";

/**
 * SSE 工具。
 * 后端三种形态：
 * 1. POST 即流（chat / papers compose / study-materials / question-library / deepthink）→ streamPost
 * 2. 任务续播 GET /api/tasks/{id}/stream?after_seq=N → streamTask
 * 3. 帧格式统一为 `data: {json}\n\n`（无 event: 字段），部分流以 `data: [DONE]` 结尾。
 */

const RESERVED_KEYS = new Set(["type", "seq", "taskId", "created_at", "trace_id", "data"]);

/** 统一信封与扁平事件归一化：{taskId,seq,type,data} 或 {type,...rest}。 */
export function normalizeEvent(json: any): TaskEvent | null {
  if (!json || typeof json !== "object") return null;
  const type = json.type;
  if (typeof type !== "string" || !type) return null;
  const extras: Record<string, any> = {};
  for (const [k, v] of Object.entries(json)) {
    if (!RESERVED_KEYS.has(k)) extras[k] = v;
  }
  let base: Record<string, any> = {};
  if (json.data !== undefined) {
    if (json.data && typeof json.data === "object" && !Array.isArray(json.data)) {
      base = json.data as Record<string, any>;
    } else {
      base = { value: json.data };
    }
  }
  return {
    type,
    data: { ...base, ...extras },
    seq: typeof json.seq === "number" ? json.seq : 0,
    taskId: typeof json.taskId === "string" ? json.taskId : undefined,
    raw: json,
  };
}

/** 增量解析 SSE 文本流，返回完整 data 载荷字符串。 */
export class SseParser {
  private buffer = "";

  push(chunk: string): string[] {
    this.buffer += chunk;
    const frames: string[] = [];
    let idx: number;
    // SSE 帧以空行分隔（兼容 \r\n）
    while ((idx = this.buffer.search(/\r?\n\r?\n/)) !== -1) {
      const frame = this.buffer.slice(0, idx);
      const sep = this.buffer.match(/\r?\n\r?\n/);
      this.buffer = this.buffer.slice(idx + (sep ? sep[0].length : 2));
      const data = frame
        .split(/\r?\n/)
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).replace(/^ /, ""))
        .join("\n");
      if (data.trim()) frames.push(data);
    }
    return frames;
  }
}

/** 流终止原因：completed = 收到 [DONE]；eof = 无 [DONE] 的普通 EOF；aborted = 前端 Abort；error = 请求/读取失败。 */
export type StreamTermination =
  | { reason: "completed" }
  | { reason: "eof" }
  | { reason: "aborted" }
  | { reason: "error"; error: Error };

export interface StreamHandlers {
  onEvent?: (ev: TaskEvent) => void;
  onDone?: () => void;
  onError?: (err: Error) => void;
  /**
   * 每次调用恰好触发一次，携带明确终止原因。
   * 兼容说明：aborted 仍会先触发 onDone（历史行为），需要区分“停止接收”的调用方应使用 onSettled。
   */
  onSettled?: (termination: StreamTermination) => void;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

/** POST 请求并把响应体当作 SSE 流读取。非 2xx 时按统一错误载荷抛 ApiError。 */
export async function streamPost(path: string, body: unknown, handlers: StreamHandlers = {}): Promise<void> {
  const { onEvent, onDone, onError, onSettled, signal, headers } = handlers;
  try {
    const res = await fetch(joinApiUrl(path), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...authHeaders(),
        ...headers,
      },
      body: JSON.stringify(body ?? {}),
      signal,
      credentials: resolveCredentials(),
    });

    if (!res.ok || !res.body) {
      let payload: any = null;
      try {
        payload = await res.json();
      } catch {
        payload = null;
      }
      const detail = payload?.detail;
      const code =
        (typeof payload?.code === "string" && payload.code) ||
        (typeof payload?.error?.code === "string" && payload.error.code) ||
        (typeof detail === "string" && /^[a-z0-9_]{1,80}$/.test(detail) ? detail : `http_${res.status}`);
      throw new ApiError({
        code,
        message: typeof payload?.message === "string" ? payload.message : typeof detail === "string" ? detail : code,
        status: res.status,
        requestId: payload?.request_id,
        details: detail ?? payload,
      });
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      for (const frame of parser.push(chunk)) {
        if (frame.trim() === "[DONE]") {
          onDone?.();
          onSettled?.({ reason: "completed" });
          return;
        }
        let json: any = null;
        try {
          json = JSON.parse(frame);
        } catch {
          continue;
        }
        const ev = normalizeEvent(json);
        if (ev) onEvent?.(ev);
      }
    }
    onDone?.();
    onSettled?.({ reason: "eof" });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      onDone?.();
      onSettled?.({ reason: "aborted" });
      return;
    }
    const normalized = err instanceof Error ? err : new Error(String(err));
    onError?.(normalized);
    onSettled?.({ reason: "error", error: normalized });
  }
}

/** GET 请求并把响应体当作 SSE 流读取；用于 study-materials 按 after_seq 刷新续播。 */
export async function streamGet(path: string, handlers: StreamHandlers = {}): Promise<void> {
  const { onEvent, onDone, onError, onSettled, signal, headers } = handlers;
  try {
    const res = await fetch(joinApiUrl(path), {
      method: "GET",
      headers: {
        Accept: "text/event-stream",
        ...authHeaders(),
        ...headers,
      },
      signal,
      credentials: resolveCredentials(),
    });

    if (!res.ok || !res.body) {
      let payload: any = null;
      try {
        payload = await res.json();
      } catch {
        payload = null;
      }
      const detail = payload?.detail;
      const code =
        (typeof payload?.code === "string" && payload.code) ||
        (typeof payload?.error?.code === "string" && payload.error.code) ||
        (typeof detail === "string" && /^[a-z0-9_]{1,80}$/.test(detail) ? detail : `http_${res.status}`);
      throw new ApiError({
        code,
        message: typeof payload?.message === "string" ? payload.message : typeof detail === "string" ? detail : code,
        status: res.status,
        requestId: payload?.request_id,
        details: detail ?? payload,
      });
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      for (const frame of parser.push(chunk)) {
        if (frame.trim() === "[DONE]") {
          onDone?.();
          onSettled?.({ reason: "completed" });
          return;
        }
        let json: any = null;
        try {
          json = JSON.parse(frame);
        } catch {
          continue;
        }
        const ev = normalizeEvent(json);
        if (ev) onEvent?.(ev);
      }
    }
    onDone?.();
    onSettled?.({ reason: "eof" });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      onDone?.();
      onSettled?.({ reason: "aborted" });
      return;
    }
    const normalized = err instanceof Error ? err : new Error(String(err));
    onError?.(normalized);
    onSettled?.({ reason: "error", error: normalized });
  }
}

export interface TaskStreamOptions {
  afterSeq?: number;
  maxRetries?: number;
  onEvent: (ev: TaskEvent) => void;
  onError?: (err: Error) => void;
  onEnd?: () => void;
}

export interface TaskStreamHandle {
  close: () => void;
}

const TERMINAL_EVENTS = new Set(["done", "result", "error"]);

/**
 * 订阅任务事件流（GET /api/tasks/{id}/stream），断线按 after_seq 重连，收到终态事件自动结束。
 */
export function streamTask(taskId: string, opts: TaskStreamOptions): TaskStreamHandle {
  let stopped = false;
  let terminal = false;
  let retries = 0;
  let lastSeq = opts.afterSeq ?? 0;
  let es: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const maxRetries = opts.maxRetries ?? 5;

  const cleanup = () => {
    es?.close();
    es = null;
  };

  const connect = () => {
    if (stopped || terminal) return;
    es = new EventSource(
      buildEventSourceUrl(`/api/tasks/${encodeURIComponent(taskId)}/stream`, { after_seq: lastSeq }),
    );
    // withCredentials 同源是 no-op；跨域部署时携带 cookie。
    // TS 的 DOM lib 将 withCredentials 声明为 readonly，但运行时浏览器允许设置，故经 Object.assign 赋值。
    Object.assign(es, { withCredentials: resolveCredentials() === "include" });
    es.onmessage = (msg) => {
      const raw = typeof msg.data === "string" ? msg.data : "";
      if (!raw || raw.trim() === "[DONE]") return;
      let json: any = null;
      try {
        json = JSON.parse(raw);
      } catch {
        return;
      }
      const ev = normalizeEvent(json);
      if (!ev) return;
      if (ev.seq) lastSeq = ev.seq;
      retries = 0;
      if (ev.type === "ping") return; // 心跳不冒泡
      opts.onEvent(ev);
      if (TERMINAL_EVENTS.has(ev.type)) {
        terminal = true;
        cleanup();
        opts.onEnd?.();
      }
    };
    es.onerror = () => {
      cleanup();
      if (stopped || terminal) return;
      if (retries < maxRetries) {
        retries += 1;
        timer = setTimeout(connect, Math.min(8000, 500 * 2 ** retries));
      } else {
        opts.onError?.(new Error("stream_disconnected"));
      }
    };
  };

  connect();
  return {
    close() {
      stopped = true;
      if (timer) clearTimeout(timer);
      cleanup();
    },
  };
}
