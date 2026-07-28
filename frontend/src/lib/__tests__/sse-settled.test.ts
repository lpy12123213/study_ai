import { afterEach, describe, expect, it, vi } from "vitest";

import { streamPost, type StreamTermination } from "@/lib/sse";

/** streamPost onSettled：区分 completed / aborted / eof / error 四种终止原因。 */

function sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamPost onSettled", () => {
  it("[DONE] → completed，onSettled 恰好一次", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(sseStream(["data: [DONE]\n\n"]), { status: 200 })));
    const settled: StreamTermination[] = [];
    let done = 0;
    await streamPost("/api/chat", {}, { onDone: () => (done += 1), onSettled: (t) => settled.push(t) });
    expect(settled).toEqual([{ reason: "completed" }]);
    expect(done).toBe(1);
  });

  it("普通 EOF → eof，兼容路径 onDone 仍触发", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(sseStream(["data: {}\n\n"]), { status: 200 })));
    const settled: StreamTermination[] = [];
    let done = 0;
    await streamPost("/api/chat", {}, { onDone: () => (done += 1), onSettled: (t) => settled.push(t) });
    expect(settled).toEqual([{ reason: "eof" }]);
    expect(done).toBe(1);
  });

  it("AbortError → aborted，兼容路径 onDone 仍触发", async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.error(new DOMException("aborted", "AbortError"));
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(stream, { status: 200 })));
    const settled: StreamTermination[] = [];
    let done = 0;
    let error: Error | null = null;
    await streamPost(
      "/api/chat",
      {},
      { onDone: () => (done += 1), onError: (e) => (error = e), onSettled: (t) => settled.push(t) },
    );
    expect(settled).toEqual([{ reason: "aborted" }]);
    expect(done).toBe(1);
    expect(error).toBeNull();
  });

  it("HTTP 错误 → error 并携带归一化异常，onDone 不触发", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "bad_request" }), {
            status: 400,
            headers: { "content-type": "application/json" },
          }),
      ),
    );
    const settled: StreamTermination[] = [];
    let done = 0;
    let error: Error | null = null;
    await streamPost(
      "/api/chat",
      {},
      { onDone: () => (done += 1), onError: (e) => (error = e), onSettled: (t) => settled.push(t) },
    );
    expect(done).toBe(0);
    expect(settled).toHaveLength(1);
    expect(settled[0].reason).toBe("error");
    expect(settled[0]).toMatchObject({ reason: "error", error });
  });
});
