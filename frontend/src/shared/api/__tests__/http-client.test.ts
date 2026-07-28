import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  apiFetch,
  authHeaders,
  buildQuery,
  configureHttpClient,
  resetHttpClient,
} from "../http-client";

/**
 * Characterization tests：固定 apiFetch 错误归一化、buildQuery 与观察者注入语义。
 * 迁移自原 lib/__tests__/api-client.test.ts（架构 Phase 1：副作用改为回调注入，
 * store 接线行为见 app/api/__tests__/http-observers.test.ts）。
 */

function jsonResponse(payload: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(payload), {
    status: init.status ?? 200,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  resetHttpClient();
  vi.unstubAllGlobals();
});

describe("buildQuery", () => {
  it("跳过 undefined / null / 空字符串并正确编码", () => {
    expect(
      buildQuery({ a: 1, b: "x y", c: undefined, d: null, e: "", f: false, g: "中文" }),
    ).toBe(`?a=1&b=x+y&f=false&g=${encodeURIComponent("中文")}`);
  });

  it("空参数返回空串", () => {
    expect(buildQuery()).toBe("");
    expect(buildQuery({})).toBe("");
  });
});

describe("apiFetch", () => {
  it("JSON 成功响应直接返回载荷", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ok: true, items: [1] })));
    await expect(apiFetch<{ ok: boolean }>("/api/x")).resolves.toEqual({ ok: true, items: [1] });
  });

  it("非 JSON 响应返回文本", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("plain", { status: 200, headers: { "content-type": "text/plain" } })),
    );
    await expect(apiFetch<string>("/api/x")).resolves.toBe("plain");
  });

  it("query 拼接到 URL", async () => {
    const spy = vi.fn(async (_input: unknown, _init?: unknown) => jsonResponse({}));
    vi.stubGlobal("fetch", spy);
    await apiFetch("/api/x", { query: { page: 2, kw: "函数" } });
    expect(spy.mock.calls[0][0]).toBe(`/api/x?page=2&kw=${encodeURIComponent("函数")}`);
  });

  it("detail 为安全 code 时直接作为错误 code", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "invalid_request" }, { status: 400 })));
    const err = await apiFetch("/api/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("invalid_request");
    expect(err.message).toBe("invalid_request");
  });

  it("detail 为人类可读文案时 code 回退 http_<status>，message 保留原文", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "参数校验失败：title 不能为空" }, { status: 422 })),
    );
    const err = await apiFetch("/api/x").catch((e) => e);
    expect(err.code).toBe("http_422");
    expect(err.message).toBe("参数校验失败：title 不能为空");
  });

  it("code/message/request_id 字段被保留", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({ code: "login_locked", message: "失败次数过多", request_id: "req-9" }, { status: 429 }),
      ),
    );
    const err = await apiFetch("/api/x", { silent: true }).catch((e) => e);
    expect(err.code).toBe("login_locked");
    expect(err.message).toBe("失败次数过多");
    expect(err.requestId).toBe("req-9");
    expect(err.isRateLimited).toBe(true);
  });

  it("error 信封形态也可归一化", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({ error: { code: "task_not_found", message: "任务不存在", request_id: "r-2" } }, { status: 404 }),
      ),
    );
    const err = await apiFetch("/api/x").catch((e) => e);
    expect(err.code).toBe("task_not_found");
    expect(err.message).toBe("任务不存在");
    expect(err.requestId).toBe("r-2");
  });

  it("网络层失败归一化为 network_error，且不触发 onError 观察者", async () => {
    const onError = vi.fn();
    configureHttpClient({ onError });
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const err = await apiFetch("/api/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("network_error");
    expect(err.status).toBe(0);
    expect(onError).not.toHaveBeenCalled();
  });

  it("AbortError 原样抛出（不归一化）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new DOMException("aborted", "AbortError"))),
    );
    const err = await apiFetch("/api/x").catch((e) => e);
    expect(err).toBeInstanceOf(DOMException);
    expect(err.name).toBe("AbortError");
  });

  it("getAccessToken 注入鉴权头；未配置时不附加 Authorization", async () => {
    const spy = vi.fn(async (_input: unknown, _init?: unknown) => jsonResponse({}));
    vi.stubGlobal("fetch", spy);

    await apiFetch("/api/x");
    expect((spy.mock.calls[0][1] as RequestInit).headers).not.toHaveProperty("Authorization");

    configureHttpClient({ getAccessToken: () => "tok-1" });
    expect(authHeaders()).toEqual({ Authorization: "Bearer tok-1" });
    await apiFetch("/api/x");
    expect((spy.mock.calls[1][1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer tok-1" });
  });

  it("HTTP 错误触发 onError 并携带 silent 标记；network_error 除外", async () => {
    const onError = vi.fn();
    configureHttpClient({ onError });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ code: "rate_limited", message: "慢点" }, { status: 429 })),
    );
    await apiFetch("/api/x").catch(() => undefined);
    expect(onError).toHaveBeenCalledTimes(1);
    const [err, ctx] = onError.mock.calls[0] as [ApiError, { silent: boolean }];
    expect(err.code).toBe("rate_limited");
    expect(ctx.silent).toBe(false);

    await apiFetch("/api/x", { silent: true }).catch(() => undefined);
    expect(onError.mock.calls[1][1]).toEqual({ silent: true });
  });

  it("成功与失败载荷均触发 onPayload 观察者", async () => {
    const onPayload = vi.fn();
    configureHttpClient({ onPayload });
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ login_required: true })));
    await apiFetch("/api/x");
    expect(onPayload).toHaveBeenCalledWith({ login_required: true });

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "invalid_request" }, { status: 400 })),
    );
    await apiFetch("/api/x").catch(() => undefined);
    expect(onPayload).toHaveBeenCalledWith({ detail: "invalid_request" });
  });

  it("baseUrl 注入 URL 前缀", async () => {
    configureHttpClient({ baseUrl: "https://api.example.com" });
    const spy = vi.fn(async (_input: unknown, _init?: unknown) => jsonResponse({}));
    vi.stubGlobal("fetch", spy);
    await apiFetch("/api/x");
    expect(spy.mock.calls[0][0]).toBe("https://api.example.com/api/x");
  });

  it("观察者抛错不阻断请求链路", async () => {
    configureHttpClient({
      onPayload: () => {
        throw new Error("observer bug");
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ok: true })));
    await expect(apiFetch<{ ok: boolean }>("/api/x")).resolves.toEqual({ ok: true });
  });
});
