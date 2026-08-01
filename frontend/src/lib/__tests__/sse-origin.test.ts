import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { streamGet, streamPost, streamTask } from "@/lib/sse";
import { watchTask } from "@/shared/streaming/task-coordinator";

/**
 * F2 SSE origin：同源默认输出与历史逐字节一致；跨域配置 VITE_API_BASE_URL 时
 * streamPost/streamGet 前置 base 且 credentials 为 include，
 * streamTask/watchTask 的 EventSource URL 前置 base 且 withCredentials=true。
 */

class FakeEventSource {
  url: string;
  withCredentials = false;
  onopen: (() => void) | null = null;
  onmessage: ((msg: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  static instances: FakeEventSource[] = [];

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {
    // no-op
  }
}

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const c of chunks) controller.enqueue(encoder.encode(c));
        controller.close();
      },
    }),
    { status: 200, headers: { "content-type": "text/event-stream" } },
  );
}

function stubFetch() {
  const spy = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
    sseResponse(["data: [DONE]\n\n"]),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

beforeEach(() => {
  FakeEventSource.instances = [];
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("streamPost / streamGet", () => {
  it("同源默认：URL 与 credentials 与历史一致", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    const spy = stubFetch();
    await streamPost("/api/chat", { message: "hi" });
    expect(spy.mock.calls[0][0]).toBe("/api/chat");
    expect((spy.mock.calls[0][1] as RequestInit).credentials).toBe("same-origin");

    await streamGet("/api/materials/refresh");
    expect(spy.mock.calls[1][0]).toBe("/api/materials/refresh");
    expect((spy.mock.calls[1][1] as RequestInit).credentials).toBe("same-origin");
  });

  it("跨域：URL 前置 base，credentials 为 include", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
    const spy = stubFetch();
    await streamPost("/api/chat", { message: "hi" });
    expect(spy.mock.calls[0][0]).toBe("https://api.example.com/api/chat");
    expect((spy.mock.calls[0][1] as RequestInit).credentials).toBe("include");

    await streamGet("/api/materials/refresh");
    expect(spy.mock.calls[1][0]).toBe("https://api.example.com/api/materials/refresh");
    expect((spy.mock.calls[1][1] as RequestInit).credentials).toBe("include");
  });
});

describe("streamTask EventSource", () => {
  it("同源默认：URL 与 withCredentials 与历史一致", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    vi.stubGlobal("EventSource", FakeEventSource);
    const handle = streamTask("task-1", { onEvent: () => {} });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/tasks/task-1/stream?after_seq=0");
    expect(FakeEventSource.instances[0].withCredentials).toBe(false);
    handle.close();
  });

  it("跨域：URL 前置 base，withCredentials 为 true", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
    vi.stubGlobal("EventSource", FakeEventSource);
    const handle = streamTask("task-1", { afterSeq: 5, onEvent: () => {} });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe(
      "https://api.example.com/api/tasks/task-1/stream?after_seq=5",
    );
    expect(FakeEventSource.instances[0].withCredentials).toBe(true);
    handle.close();
  });
});

describe("watchTask EventSource", () => {
  it("同源默认：URL 与 withCredentials 与历史一致", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    vi.stubGlobal("EventSource", FakeEventSource);
    const handle = watchTask("task-1", {
      getStatus: async () => ({ status: "running" }),
      onEvent: () => {},
    });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/tasks/task-1/stream?after_seq=0");
    expect(FakeEventSource.instances[0].withCredentials).toBe(false);
    handle.close();
  });

  it("跨域：URL 前置 base，withCredentials 为 true", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
    vi.stubGlobal("EventSource", FakeEventSource);
    const handle = watchTask("task-1", {
      getStatus: async () => ({ status: "running" }),
      onEvent: () => {},
    });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe(
      "https://api.example.com/api/tasks/task-1/stream?after_seq=0",
    );
    expect(FakeEventSource.instances[0].withCredentials).toBe(true);
    handle.close();
  });
});
