import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { matchPath } from "react-router";
import { describe, expect, it } from "vitest";

import { APP_ROUTES, REDIRECTS } from "../catalog";

/**
 * F11 文档契约检查：USER_GUIDE.md 的每个「入口」都必须在 APP_ROUTES、
 * REDIRECTS.from 或「规划中」白名单中找到归宿，防止指南路由再次漂移到 404。
 * 文档由 docs agent 负责维护；本测试只读校验，不修改文档。
 * 本测试在 frontend/ 下运行（cwd = frontend），文档位于 ../docs/USER_GUIDE.md。
 */
const GUIDE_PATH = resolve(process.cwd(), "../docs/USER_GUIDE.md");

/** 指南中标记「规划中」、尚无路由/重定向的页面。 */
const PLANNED_PATHS = ["/lesson-plans", "/canvas", "/knowledge-videos"];

/**
 * 解析文档中所有「入口：<path>」行：去掉 markdown 反引号后，取首个路径字段，
 * 忽略 query 与尾部说明文字（如「（旧 /blueprint 自动跳转）」）。
 */
function entryPaths(doc: string): string[] {
  return doc
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("入口："))
    .map((line) => line.slice("入口：".length).trim())
    .map((line) => line.replace(/`/g, ""))
    .map((line) => line.match(/^\/([^\s?（）()]*)/)?.[0] ?? "")
    .filter(Boolean);
}

describe("USER_GUIDE 入口与路由一致性", () => {
  const doc = readFileSync(GUIDE_PATH, "utf8");
  const entries = entryPaths(doc);

  it("指南至少声明了 3 个入口", () => {
    expect(entries.length).toBeGreaterThanOrEqual(3);
  });

  it("每个入口都能匹配 APP_ROUTES、REDIRECTS 或规划中白名单", () => {
    for (const entry of entries) {
      const routed = APP_ROUTES.some((route) => matchPath({ path: route.path, end: true }, entry));
      const redirected = REDIRECTS.some((r) => r.from === entry);
      expect(
        routed || redirected || PLANNED_PATHS.includes(entry),
        `指南入口 ${entry} 不在 APP_ROUTES、REDIRECTS 或规划中白名单内`,
      ).toBe(true);
    }
  });
});
