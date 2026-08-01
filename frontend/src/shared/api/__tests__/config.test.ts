import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildEventSourceUrl,
  isCrossOrigin,
  joinApiUrl,
  resolveApiBaseUrl,
  resolveCredentials,
} from "../config";

/**
 * F2 统一 API origin 配置：VITE_API_BASE_URL 规范化、跨域判定、
 * joinApiUrl 双 /api 防重与 buildEventSourceUrl 查询串。
 */

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("resolveApiBaseUrl", () => {
  it("未配置时返回空串（同源默认，路径已自带 /api）", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    expect(resolveApiBaseUrl()).toBe("");
  });

  it("去除首尾空白与结尾 /", () => {
    vi.stubEnv("VITE_API_BASE_URL", "  https://api.example.com/  ");
    expect(resolveApiBaseUrl()).toBe("https://api.example.com");
  });

  it("剥离结尾 /api 后缀（含 /api/）", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com/api");
    expect(resolveApiBaseUrl()).toBe("https://api.example.com");
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com/api/");
    expect(resolveApiBaseUrl()).toBe("https://api.example.com");
  });

  it("绝对 origin 原样保留", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
    expect(resolveApiBaseUrl()).toBe("https://api.example.com");
  });

  it("相对前缀（/backend）保留", () => {
    vi.stubEnv("VITE_API_BASE_URL", "/backend");
    expect(resolveApiBaseUrl()).toBe("/backend");
  });
});

describe("isCrossOrigin / resolveCredentials", () => {
  it("同源默认返回 same-origin", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    expect(isCrossOrigin()).toBe(false);
    expect(resolveCredentials()).toBe("same-origin");
  });

  it("相对前缀不是跨域", () => {
    vi.stubEnv("VITE_API_BASE_URL", "/backend");
    expect(isCrossOrigin()).toBe(false);
    expect(resolveCredentials()).toBe("same-origin");
  });

  it("绝对 origin 是跨域 → include", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
    expect(isCrossOrigin()).toBe(true);
    expect(resolveCredentials()).toBe("include");
  });

  it("协议相对 // 视为跨域", () => {
    vi.stubEnv("VITE_API_BASE_URL", "//api.example.com");
    expect(isCrossOrigin()).toBe(true);
    expect(resolveCredentials()).toBe("include");
  });
});

describe("joinApiUrl", () => {
  it("默认 base（同源）原样返回 /api 路径", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    expect(joinApiUrl("/api/conversations")).toBe("/api/conversations");
  });

  it("前置 base 前缀", () => {
    expect(joinApiUrl("/api/conversations", "https://api.example.com")).toBe(
      "https://api.example.com/api/conversations",
    );
  });

  it("base 结尾 /api 且 path 开头 /api 时不重复", () => {
    expect(joinApiUrl("/api/conversations", "https://api.example.com/api")).toBe(
      "https://api.example.com/api/conversations",
    );
  });

  it("base 结尾 / 时不产生 //", () => {
    expect(joinApiUrl("/api/conversations", "https://api.example.com/")).toBe(
      "https://api.example.com/api/conversations",
    );
  });

  it("相对前缀正常拼接", () => {
    expect(joinApiUrl("/api/conversations", "/backend")).toBe("/backend/api/conversations");
  });
});

describe("buildEventSourceUrl", () => {
  it("拼接查询串", () => {
    expect(buildEventSourceUrl("/api/tasks/t-1/stream", { after_seq: 3 })).toBe(
      "/api/tasks/t-1/stream?after_seq=3",
    );
  });

  it("空查询时不追加 ?", () => {
    expect(buildEventSourceUrl("/api/tasks/t-1/stream")).toBe("/api/tasks/t-1/stream");
  });

  it("跨域 base 前置且保留查询", () => {
    expect(
      buildEventSourceUrl("/api/tasks/t-1/stream", { after_seq: 3 }, "https://api.example.com"),
    ).toBe("https://api.example.com/api/tasks/t-1/stream?after_seq=3");
  });
});
