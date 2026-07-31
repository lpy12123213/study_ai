import { useRef, useState } from "react";
import { tasksApi } from "@/features/task-center/api";
import type { TaskEvent } from "@/shared/api/types";
import type { StreamHandlers } from "@/lib/sse";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";


// ---------------- 流式任务 hook（POST 即流 → tasks store） ----------------

export function useTaskStream(type: string) {
  const toast = useUiStore((s) => s.toast);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const start = (
    title: string,
    run: (handlers: StreamHandlers) => void,
    opts?: {
      onEvent?: (ev: TaskEvent) => void;
      onDoneEvent?: (data: any) => void;
      onError?: (err: Error) => void;
    },
  ) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setTaskId(null);
    let localId = "";
    run({
      signal: controller.signal,
      onEvent: (ev) => {
        if (ev.taskId && !localId) {
          localId = ev.taskId;
          setTaskId(ev.taskId);
          useTasksStore.getState().register(ev.taskId, { type, title });
        }
        if (localId) useTasksStore.getState().applyEvent(localId, ev);
        opts?.onEvent?.(ev);
        if (ev.type === "done" || ev.type === "result") {
          opts?.onDoneEvent?.(ev.data ?? {});
        }
      },
      onDone: () => setRunning(false),
      onError: (err) => {
        setRunning(false);
        if (opts?.onError) opts.onError(err);
        else toast({ title: "任务失败", description: err.message || "流式任务异常中断", variant: "destructive" });
      },
    });
  };

  const stop = () => {
    abortRef.current?.abort();
    // abort 只断开前端流，服务端任务仍在运行——尽力经任务中心取消（题库任务注册在共享任务运行时）
    if (taskId) {
      tasksApi.cancel(taskId).catch(() => undefined);
    }
  };

  return { taskId, running, start, stop };
}

