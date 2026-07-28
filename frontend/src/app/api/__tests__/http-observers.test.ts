import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { registerHttpObservers } from "@/app/api/http-observers";
import { apiFetch, resetHttpClient } from "@/shared/api/http-client";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

/** app 层接线行为：鉴权头注入、429 toast、组卷网登录态标记。 */

function jsonResponse(payload: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(payload), {
    status: init.status ?? 200,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  useUiStore.setState({ toasts: [], zujuanLoginRequired: false });
  useAuthStore.setState({ token: null });
  registerHttpObservers();
});

afterEach(() => {
  resetHttpClient();
  vi.unstubAllGlobals();
});

describe("registerHttpObservers", () => {
  it("auth store 有 token 时请求携带 Authorization 头", async () => {
    useAuthStore.setState({ token: "tok-9" });
    const spy = vi.fn(async (_input: unknown, _init?: unknown) => jsonResponse({}));
    vi.stubGlobal("fetch", spy);
    await apiFetch("/api/x");
    expect((spy.mock.calls[0][1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer tok-9" });
  });

  it("429 且未 silent 时推送限流 toast", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ code: "rate_limited", message: "慢点" }, { status: 429 })),
    );
    await apiFetch("/api/x").catch(() => undefined);
    const toasts = useUiStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].variant).toBe("warning");
    expect(toasts[0].title).toBe("请求过于频繁");
  });

  it("429 login_locked 使用锁定文案", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ code: "login_locked", message: "锁定" }, { status: 429 })),
    );
    await apiFetch("/api/x").catch(() => undefined);
    expect(useUiStore.getState().toasts[0].title).toBe("登录已锁定");
  });

  it("silent 时不推送 toast", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ code: "rate_limited", message: "慢点" }, { status: 429 })),
    );
    await apiFetch("/api/x", { silent: true }).catch(() => undefined);
    expect(useUiStore.getState().toasts).toHaveLength(0);
  });

  it("非 429 错误不推送 toast", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "invalid_request" }, { status: 400 })),
    );
    await apiFetch("/api/x").catch(() => undefined);
    expect(useUiStore.getState().toasts).toHaveLength(0);
  });

  it("成功或失败载荷中的 login_required / cookie_expired 标记会置位组卷网提示", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ login_required: true })));
    await apiFetch("/api/x");
    expect(useUiStore.getState().zujuanLoginRequired).toBe(true);

    useUiStore.setState({ zujuanLoginRequired: false });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ cookie_expired: true }, { status: 400 })),
    );
    await apiFetch("/api/x").catch(() => undefined);
    expect(useUiStore.getState().zujuanLoginRequired).toBe(true);
  });
});
