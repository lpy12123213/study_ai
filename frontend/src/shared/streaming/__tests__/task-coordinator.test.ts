/**
 * Task Coordinator 连接层测试：seq 去重、终态收敛、EOF 后 REST 校准、
 * running 才重连、paused/pending_review 停止连接不误判终态。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { watchTask, type TaskRestStatus } from "../task-coordinator";
import type { TaskEvent } from "@/shared/api/types";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((msg: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  fail() {
    this.onerror?.();
  }
}

function lastSource(): FakeEventSource {
  const inst = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  if (!inst) throw new Error("no EventSource created");
  return inst;
}

async function flushMicrotasks() {
  await Promise.resolve();
  await Promise.resolve();
}

describe("watchTask", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const neverStatus = () => new Promise<TaskRestStatus>(() => {});

  it("转发事件并按 seq 去重；ping 不冒泡", () => {
    const events: TaskEvent[] = [];
    const handle = watchTask("t1", { getStatus: neverStatus, onEvent: (ev) => events.push(ev) });

    const es = lastSource();
    es.emit({ taskId: "t1", seq: 1, type: "status", data: { content: "a" } });
    es.emit({ taskId: "t1", seq: 1, type: "status", data: { content: "重复" } });
    es.emit({ taskId: "t1", seq: 1, type: "ping", data: {} });
    es.emit({ taskId: "t1", seq: 2, type: "progress", data: { progress: 40 } });

    expect(events.map((e) => e.type)).toEqual(["status", "progress"]);
    handle.close();
  });

  it("事件终态（done）→ onTerminal(event) 并关闭连接", () => {
    const onTerminal = vi.fn();
    watchTask("t1", { getStatus: neverStatus, onEvent: () => {}, onTerminal });

    const es = lastSource();
    es.emit({ taskId: "t1", seq: 1, type: "done", data: { success: true } });

    expect(onTerminal).toHaveBeenCalledWith("event");
    expect(es.closed).toBe(true);
  });

  it("断线后校准：running 才按 after_seq 重连", async () => {
    const getStatus = vi.fn().mockResolvedValue({ status: "running" });
    watchTask("t1", { getStatus, onEvent: () => {} });

    const first = lastSource();
    first.emit({ taskId: "t1", seq: 7, type: "status", data: { content: "a" } });
    first.fail();
    await flushMicrotasks();
    expect(getStatus).toHaveBeenCalledWith("t1");

    await vi.advanceTimersByTimeAsync(1_100);
    const second = lastSource();
    expect(second).not.toBe(first);
    expect(second.url).toContain("after_seq=7");
  });

  it("校准得到 paused：onCalibrated 触发、不重连、不判终态", async () => {
    const onCalibrated = vi.fn();
    const onTerminal = vi.fn();
    const getStatus = vi.fn().mockResolvedValue({ status: "paused" });
    watchTask("t1", { getStatus, onEvent: () => {}, onCalibrated, onTerminal });

    lastSource().fail();
    await flushMicrotasks();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(onCalibrated).toHaveBeenCalledWith({ status: "paused" });
    expect(onTerminal).not.toHaveBeenCalled();
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("校准得到 completed：onCalibrated + onTerminal(calibration)", async () => {
    const onCalibrated = vi.fn();
    const onTerminal = vi.fn();
    const getStatus = vi.fn().mockResolvedValue({ status: "completed", result: { ok: true } });
    watchTask("t1", { getStatus, onEvent: () => {}, onCalibrated, onTerminal });

    lastSource().fail();
    await flushMicrotasks();

    expect(onCalibrated).toHaveBeenCalledWith({ status: "completed", result: { ok: true } });
    expect(onTerminal).toHaveBeenCalledWith("calibration");
  });

  it("校准得到 canceled：onCalibrated + onTerminal(calibration)，无需终态事件", async () => {
    const onCalibrated = vi.fn();
    const onTerminal = vi.fn();
    const getStatus = vi.fn().mockResolvedValue({ status: "canceled", error: "Task cancelled" });
    watchTask("t1", { getStatus, onEvent: () => {}, onCalibrated, onTerminal });

    lastSource().fail();
    await flushMicrotasks();

    expect(onCalibrated).toHaveBeenCalledWith({ status: "canceled", error: "Task cancelled" });
    expect(onTerminal).toHaveBeenCalledWith("calibration");
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("校准失败重试耗尽 → onGaveUp", async () => {
    const onGaveUp = vi.fn();
    const getStatus = vi.fn().mockRejectedValue(new Error("network"));
    watchTask("t1", { getStatus, onEvent: () => {}, onGaveUp, maxReconnects: 1 });

    lastSource().fail();
    await flushMicrotasks();
    await vi.advanceTimersByTimeAsync(2_000);
    lastSource().fail();
    await flushMicrotasks();

    expect(onGaveUp).toHaveBeenCalled();
  });

  it("close() 后不再重连", async () => {
    const getStatus = vi.fn().mockResolvedValue({ status: "running" });
    const handle = watchTask("t1", { getStatus, onEvent: () => {} });

    handle.close();
    lastSource().fail();
    await flushMicrotasks();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(FakeEventSource.instances).toHaveLength(1);
  });
});
