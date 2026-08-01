import { afterEach, describe, expect, it, vi } from "vitest";

import { generatedFileUrl, proxyImageUrl } from "../media";

/**
 * F2 媒体 URL：同源默认输出与历史逐字节一致；
 * 跨域配置 VITE_API_BASE_URL 时 /api/media/... 前置 origin。
 */

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("proxyImageUrl", () => {
  it("同源默认：外部 http 图经 SSRF 代理，输出与历史一致", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    const src = "https://example.com/question.png";
    expect(proxyImageUrl(src)).toBe(`/api/media/proxy?url=${encodeURIComponent(src)}`);
    expect(proxyImageUrl("/api/media/generated/a.png")).toBe("/api/media/generated/a.png");
    expect(proxyImageUrl("//cdn.example.com/x.png")).toBe(
      `/api/media/proxy?url=${encodeURIComponent("https://cdn.example.com/x.png")}`,
    );
    expect(proxyImageUrl("")).toBe("");
    expect(proxyImageUrl(undefined)).toBe("");
    expect(proxyImageUrl("relative.png")).toBe("relative.png");
  });

  it("跨域：代理地址与既有 /api 路径前置 origin", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
    const src = "https://example.com/question.png";
    expect(proxyImageUrl(src)).toBe(
      `https://api.example.com/api/media/proxy?url=${encodeURIComponent(src)}`,
    );
    expect(proxyImageUrl("/api/media/generated/a.png")).toBe(
      "https://api.example.com/api/media/generated/a.png",
    );
  });
});

describe("generatedFileUrl", () => {
  it("同源默认：输出与历史一致", () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    expect(generatedFileUrl("report.pdf")).toBe("/api/media/generated/report.pdf");
    expect(generatedFileUrl("/api/media/generated/report.pdf")).toBe(
      "/api/media/generated/report.pdf",
    );
    expect(generatedFileUrl("")).toBe("");
    expect(generatedFileUrl(undefined)).toBe("");
  });

  it("跨域：生成文件地址前置 origin", () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.com");
    expect(generatedFileUrl("report.pdf")).toBe(
      "https://api.example.com/api/media/generated/report.pdf",
    );
    expect(generatedFileUrl("/api/media/generated/report.pdf")).toBe(
      "https://api.example.com/api/media/generated/report.pdf",
    );
  });
});
