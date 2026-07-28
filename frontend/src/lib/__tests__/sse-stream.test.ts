import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/http-client";
import { streamPost } from "@/lib/sse";
import type { TaskEvent } from "@/shared/api/types";

/**
 * Characterization tests：固定 streamPost 当前终止语义。
 * 注意：当前实现把 [DONE]、普通 EOF 与 AbortError 都汇入 onDone（见计划 §9.2），
 * 后续扩展终止原因时必须保持这些用例的兼容路径。
 */

function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

function sseResponse(chunks: string[], init: { status?: number } = {}): Response {
  return new Response(sseStream(chunks), {
    status: init.status ?? 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function stubFetch(res: Response | (() => Response | Promise<Response>)) {
  const spy = vi.fn(async () => (typeof res === "function" ? await res() : res));
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamPost", () => {
  it("逐帧解析 JSON 事件并归一化", async () => {
    stubFetch(
      sseResponse([
        'data: {"type":"stream_start","iteration":1}\n\n',
        'data: {"type":"text_delta","content":"你"}\n\ndata: {"type":"text_delta","content":"好"}\n\n',
        "data: [DONE]\n\n",
      ]),
    );
    const events: TaskEvent[] = [];
    let done = 0;
    await streamPost(
      "/api/chat",
      { message: "hi" },
      { onEvent: (ev) => events.push(ev), onDone: () => (done += 1) },
    );
    expect(events.map((e) => e.type)).toEqual(["stream_start", "text_delta", "text_delta"]);
    expect(events[1].data).toEqual({ content: "你" });
    expect(done).toBe(1);
  });

  it("以 POST + JSON + SSE Accept 头发送请求", async () => {
    const spy = stubFetch(sseResponse(["data: [DONE]\n\n"]));
    await streamPost("/api/chat", { message: "hi", n: 1 }, {});
    const [url, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/chat");
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    });
    expect(JSON.parse(String(init.body))).toEqual({ message: "hi", n: 1 });
  });

  it("[DONE] 之后不再处理后续帧，且 onDone 只触发一次", async () => {
    stubFetch(
      sseResponse([
        "data: [DONE]\n\n",
        'data: {"type":"text_delta","content":"不应出现"}\n\n',
      ]),
    );
    const events: TaskEvent[] = [];
    let done = 0;
    await streamPost("/api/chat", {}, { onEvent: (ev) => events.push(ev), onDone: () => (done += 1) });
    expect(events).toEqual([]);
    expect(done).toBe(1);
  });

  it("无 [DONE] 的普通 EOF 也触发 onDone（当前语义）", async () => {
    stubFetch(sseResponse(['data: {"type":"text_delta","content":"x"}\n\n']));
    let done = 0;
    await streamPost("/api/chat", {}, { onDone: () => (done += 1) });
    expect(done).toBe(1);
  });

  it("流中 AbortError 汇入 onDone 而非 onError（当前语义）", async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"text_delta","content":"a"}\n\n'));
        controller.error(new DOMException("The operation was aborted.", "AbortError"));
      },
    });
    stubFetch(new Response(stream, { status: 200 }));
    let done = 0;
    let error: Error | null = null;
    await streamPost(
      "/api/chat",
      {},
      { onDone: () => (done += 1), onError: (e) => (error = e) },
    );
    expect(done).toBe(1);
    expect(error).toBeNull();
  });

  it("非法 JSON 帧被跳过，不影响后续帧", async () => {
    stubFetch(
      sseResponse(["data: {broken\n\n", 'data: {"type":"text_delta","content":"ok"}\n\n', "data: [DONE]\n\n"]),
    );
    const events: TaskEvent[] = [];
    await streamPost("/api/chat", {}, { onEvent: (ev) => events.push(ev) });
    expect(events.map((e) => e.type)).toEqual(["text_delta"]);
  });

  it("非 2xx：按统一错误载荷抛 ApiError 进 onError", async () => {
    stubFetch(
      new Response(JSON.stringify({ code: "rate_limited", message: "请求过于频繁", request_id: "req-1" }), {
        status: 429,
        headers: { "content-type": "application/json" },
      }),
    );
    let error: Error | null = null;
    let done = 0;
    await streamPost("/api/chat", {}, { onError: (e) => (error = e), onDone: () => (done += 1) });
    expect(done).toBe(0);
    expect(error).toBeInstanceOf(ApiError);
    const apiErr = error as unknown as ApiError;
    expect(apiErr.code).toBe("rate_limited");
    expect(apiErr.status).toBe(429);
    expect(apiErr.requestId).toBe("req-1");
  });

  it("非 2xx 且 detail 为人类可读文案时 code 回退 http_<status>", async () => {
    stubFetch(
      new Response(JSON.stringify({ detail: "服务器繁忙，请稍后再试" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      }),
    );
    let error: Error | null = null;
    await streamPost("/api/chat", {}, { onError: (e) => (error = e) });
    const apiErr = error as unknown as ApiError;
    expect(apiErr.code).toBe("http_503");
    expect(apiErr.message).toBe("服务器繁忙，请稍后再试");
  });
});
