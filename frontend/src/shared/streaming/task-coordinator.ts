/**
 * Task Coordinator 连接层（架构 Phase 3）。
 *
 * 职责（规划 §10.3–10.4）：
 * - 按 taskId 建立 GET /api/tasks/{id}/stream 的 EventSource 连接；
 * - seq 去重与乱序保护；断线按 after_seq 指数退避重连；
 * - EOF 不是 completed：断线/EOF 后先 REST 校准任务状态，
 *   仅 status === running 才重连；paused / pending_review 保留投影并停止连接；
 * - 事件终态（done/result/error）或校准终态后通知调用方（触发 query invalidation）。
 *
 * 本模块是纯连接编排：REST 校准函数由调用方注入，不导入业务 API 与 store。
 */
import { normalizeEvent } from "@/lib/sse";
import { buildEventSourceUrl, resolveCredentials } from "@/shared/api/config";
import type { TaskEvent } from "@/shared/api/types";

export type TaskConnectionState = "connecting" | "open" | "reconnecting" | "stopped";

export interface TaskRestStatus {
  status: string;
  result?: unknown;
  error?: unknown;
}

export interface TaskWatchOptions {
  afterSeq?: number;
  /** EOF/断线后的 REST 状态校准（通常注入 tasksApi.get）。 */
  getStatus: (taskId: string) => Promise<TaskRestStatus>;
  onEvent: (ev: TaskEvent) => void;
  onConnectionChange?: (state: TaskConnectionState) => void;
  /** 校准发现任务不在 running 时回调（paused/pending_review/终态），投影据此对齐。 */
  onCalibrated?: (rest: TaskRestStatus) => void;
  /** 任务终局（事件终态或校准终态）后触发恰好一次。 */
  onTerminal?: (via: "event" | "calibration") => void;
  /** 重连与校准均无法推进后放弃。 */
  onGaveUp?: (err: Error) => void;
  maxReconnects?: number;
}

export interface TaskWatchHandle {
  close: () => void;
}

const TERMINAL_EVENT_TYPES = new Set(["done", "result", "error"]);
const TERMINAL_REST_STATUSES = new Set(["completed", "failed", "canceled", "cancelled"]);

export function watchTask(taskId: string, opts: TaskWatchOptions): TaskWatchHandle {
  let stopped = false;
  let finished = false;
  let lastSeq = opts.afterSeq ?? 0;
  let reconnects = 0;
  const maxReconnects = opts.maxReconnects ?? 6;
  let es: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const setConn = (state: TaskConnectionState) => opts.onConnectionChange?.(state);

  const cleanup = () => {
    es?.close();
    es = null;
  };

  const finish = (via: "event" | "calibration") => {
    if (finished) return;
    finished = true;
    cleanup();
    setConn("stopped");
    opts.onTerminal?.(via);
  };

  const giveUp = () => {
    cleanup();
    setConn("stopped");
    opts.onGaveUp?.(new Error("stream_disconnected"));
  };

  const scheduleReconnect = () => {
    reconnects += 1;
    timer = setTimeout(connect, Math.min(8000, 500 * 2 ** reconnects));
  };

  /** EOF/断线后的状态校准：running 才重连，其余按 REST 状态收敛。 */
  const calibrate = async () => {
    if (stopped || finished) return;
    setConn("reconnecting");
    let rest: TaskRestStatus | null = null;
    try {
      rest = await opts.getStatus(taskId);
    } catch {
      rest = null;
    }
    if (stopped || finished) return;
    if (!rest || String(rest.status || "") === "running") {
      if (reconnects < maxReconnects) scheduleReconnect();
      else giveUp();
      return;
    }
    opts.onCalibrated?.(rest);
    if (TERMINAL_REST_STATUSES.has(String(rest.status))) {
      finish("calibration");
    } else {
      // paused / pending_review：保留投影，停止连接（恢复由用户操作重新 watch）
      cleanup();
      setConn("stopped");
    }
  };

  const connect = () => {
    if (stopped || finished) return;
    setConn(reconnects > 0 ? "reconnecting" : "connecting");
    es = new EventSource(
      buildEventSourceUrl(`/api/tasks/${encodeURIComponent(taskId)}/stream`, { after_seq: lastSeq }),
    );
    // withCredentials 同源是 no-op；跨域部署时携带 cookie。
    // TS 的 DOM lib 将 withCredentials 声明为 readonly，但运行时浏览器允许设置，故经 Object.assign 赋值。
    Object.assign(es, { withCredentials: resolveCredentials() === "include" });
    es.onopen = () => setConn("open");
    es.onmessage = (msg) => {
      const raw = typeof msg.data === "string" ? msg.data : "";
      if (!raw || raw.trim() === "[DONE]") return;
      let json: unknown = null;
      try {
        json = JSON.parse(raw);
      } catch {
        return;
      }
      const ev = normalizeEvent(json);
      if (!ev) return;
      if (ev.type === "ping") {
        reconnects = 0;
        return;
      }
      // 去重/乱序保护：重连重放期间丢弃已消费序号
      if (ev.seq && ev.seq <= lastSeq) return;
      if (ev.seq) lastSeq = ev.seq;
      reconnects = 0;
      opts.onEvent(ev);
      if (TERMINAL_EVENT_TYPES.has(ev.type)) finish("event");
    };
    es.onerror = () => {
      cleanup();
      if (stopped || finished) return;
      void calibrate();
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
