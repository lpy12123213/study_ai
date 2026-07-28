import { create } from "zustand";

import { queryClient } from "@/app/providers/query-client";
import { tasksApi } from "@/features/task-center/api";
import { normalizeProgress } from "@/lib/format";
import { watchTask, type TaskRestStatus, type TaskWatchHandle } from "@/shared/streaming/task-coordinator";
import type { TaskEvent, TaskStatus, TaskStep } from "@/shared/api/types";

const MAX_EVENTS = 300;
const MAX_TEXT = 200_000;

export interface ActiveTask {
  taskId: string;
  type: string;
  title: string;
  status: TaskStatus;
  progress: number;
  steps: TaskStep[];
  /** 近期事件（封顶 MAX_EVENTS），供时间线展示 */
  events: TaskEvent[];
  /** 增量文本（text_delta / answer_delta 追加） */
  text: string;
  /** 推理流（reasoning_delta / thinking 追加） */
  reasoning: string;
  statusText: string;
  result?: any;
  error?: string | null;
  composeDraft?: any;
  lastSeq: number;
  streaming: boolean;
}

interface TasksState {
  active: Record<string, ActiveTask>;
  register: (taskId: string, meta?: { type?: string; title?: string }) => ActiveTask;
  applyEvent: (taskId: string, ev: TaskEvent) => void;
  setStatus: (taskId: string, status: TaskStatus) => void;
  /** EOF/断线后的 REST 校准结果对齐投影（Coordinator 回调）。 */
  calibrate: (taskId: string, rest: TaskRestStatus) => void;
  remove: (taskId: string) => void;
  /** 打开任务事件流（幂等），返回是否新开启 */
  watch: (taskId: string, meta?: { type?: string; title?: string }) => void;
  unwatch: (taskId: string) => void;
}

const handles = new Map<string, TaskWatchHandle>();

function emptyTask(taskId: string, meta?: { type?: string; title?: string }): ActiveTask {
  return {
    taskId,
    type: meta?.type ?? "",
    title: meta?.title ?? "",
    status: "running",
    progress: 0,
    steps: [],
    events: [],
    text: "",
    reasoning: "",
    statusText: "",
    result: undefined,
    error: null,
    composeDraft: undefined,
    lastSeq: 0,
    streaming: false,
  };
}

export const useTasksStore = create<TasksState>()((set, get) => ({
  active: {},

  register: (taskId, meta) => {
    const existing = get().active[taskId];
    if (existing) return existing;
    const task = emptyTask(taskId, meta);
    set((s) => ({ active: { ...s.active, [taskId]: task } }));
    return task;
  },

  applyEvent: (taskId, ev) => {
    set((s) => {
      const prev = s.active[taskId] ?? emptyTask(taskId);
      // seq 去重（Coordinator 已过滤一层，这里防御直接调用方）
      if (ev.seq && ev.seq <= prev.lastSeq) return s;
      const next: ActiveTask = { ...prev, events: [...prev.events.slice(-(MAX_EVENTS - 1)), ev] };
      if (ev.seq) next.lastSeq = Math.max(next.lastSeq, ev.seq);
      const d = ev.data ?? {};

      switch (ev.type) {
        case "step": {
          const step = d.step ?? d;
          if (step && typeof step === "object" && step.id) {
            const idx = next.steps.findIndex((x) => x.id === step.id);
            if (idx >= 0) {
              next.steps = next.steps.map((x, i) => (i === idx ? { ...x, ...step } : x));
            } else {
              next.steps = [...next.steps, step as TaskStep];
            }
          }
          break;
        }
        case "progress": {
          const p = d.progress ?? d.percent ?? d.value;
          next.progress = normalizeProgress(typeof p === "number" ? p : next.progress / 100 > 1 ? next.progress : p);
          if (typeof p === "number") next.progress = normalizeProgress(p);
          break;
        }
        case "status": {
          next.statusText = String(d.content ?? d.message ?? next.statusText);
          break;
        }
        case "text_delta":
        case "answer_delta": {
          const c = typeof d.content === "string" ? d.content : "";
          if (c) next.text = (next.text + c).slice(-MAX_TEXT);
          break;
        }
        case "reasoning_delta":
        case "thinking":
        case "thinking_delta": {
          const c = typeof d.content === "string" ? d.content : "";
          if (c) next.reasoning = (next.reasoning + c).slice(-MAX_TEXT);
          break;
        }
        case "pending_review": {
          next.status = "pending_review";
          next.composeDraft = d.composeDraft ?? ev.raw?.composeDraft ?? next.composeDraft;
          break;
        }
        case "done":
        case "result": {
          if (next.status !== "pending_review") next.status = "completed";
          next.progress = 100;
          next.result = d.result ?? d;
          break;
        }
        case "error": {
          next.status = "failed";
          next.error = String(d.error ?? d.message ?? "未知错误");
          break;
        }
        case "warning": {
          break;
        }
        default:
          break;
      }
      return { active: { ...s.active, [taskId]: next } };
    });
  },

  setStatus: (taskId, status) =>
    set((s) => {
      const prev = s.active[taskId];
      if (!prev) return s;
      return { active: { ...s.active, [taskId]: { ...prev, status } } };
    }),

  calibrate: (taskId, rest) =>
    set((s) => {
      const prev = s.active[taskId];
      if (!prev) return s;
      const status = String(rest.status || "") as TaskStatus;
      const next: ActiveTask = { ...prev, status };
      if (status === "completed") {
        next.progress = 100;
        if (rest.result !== undefined && next.result === undefined) next.result = rest.result;
      }
      if (status === "failed" && rest.error != null && !next.error) {
        next.error = typeof rest.error === "string" ? rest.error : JSON.stringify(rest.error);
      }
      return { active: { ...s.active, [taskId]: next } };
    }),

  remove: (taskId) => {
    handles.get(taskId)?.close();
    handles.delete(taskId);
    set((s) => {
      const next = { ...s.active };
      delete next[taskId];
      return { active: next };
    });
  },

  watch: (taskId, meta) => {
    if (handles.has(taskId)) return;
    get().register(taskId, meta);
    set((s) => {
      const prev = s.active[taskId];
      return prev ? { active: { ...s.active, [taskId]: { ...prev, streaming: true } } } : s;
    });
    const markStopped = () => {
      handles.delete(taskId);
      set((s) => {
        const prev = s.active[taskId];
        return prev ? { active: { ...s.active, [taskId]: { ...prev, streaming: false } } } : s;
      });
    };
    const handle = watchTask(taskId, {
      afterSeq: get().active[taskId]?.lastSeq ?? 0,
      getStatus: async (id) => {
        const detail = await tasksApi.get(id);
        return { status: String(detail.status || ""), result: detail.result, error: detail.error };
      },
      onEvent: (ev) => get().applyEvent(taskId, ev),
      onCalibrated: (rest) => {
        get().calibrate(taskId, rest);
        const status = String(rest.status || "");
        // paused / pending_review：投影保留、连接停止，允许后续重新 watch 续播
        if (status === "paused" || status === "pending_review") markStopped();
      },
      onTerminal: () => {
        markStopped();
        // 终态后统一失效任务列表/详情查询（架构 Phase 3）
        void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      },
      onConnectionChange: (state) => {
        if (state === "stopped") return; // 终态/放弃由对应回调收尾
        set((s) => {
          const prev = s.active[taskId];
          return prev ? { active: { ...s.active, [taskId]: { ...prev, streaming: true } } } : s;
        });
      },
      onGaveUp: markStopped,
    });
    handles.set(taskId, handle);
  },

  unwatch: (taskId) => {
    handles.get(taskId)?.close();
    handles.delete(taskId);
    set((s) => {
      const prev = s.active[taskId];
      return prev ? { active: { ...s.active, [taskId]: { ...prev, streaming: false } } } : s;
    });
  },
}));
