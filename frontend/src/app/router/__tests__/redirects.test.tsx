import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter, redirect, type RouteObject } from "react-router";
import { describe, expect, it } from "vitest";

import { APP_ROUTES, REDIRECTS } from "../catalog";

/**
 * F11 兼容重定向：REDIRECTS 顶层 redirect 路由 + 全部 APP_ROUTES 的占位页，
 * 与 router.tsx 结构同构但不加载真实页面。只验证命中 from 后落到 to。
 */
function buildTestRouter(initialPath: string) {
  const routes: RouteObject[] = [
    ...REDIRECTS.map((r) => ({ path: r.from, loader: () => redirect(r.to) })),
    ...APP_ROUTES.map((meta) => ({ path: meta.path, element: <div data-testid={`page-${meta.id}`} /> })),
  ];
  return createMemoryRouter(routes, { initialEntries: [initialPath] });
}

describe("兼容重定向", () => {
  it.each([
    { from: "/blueprint", to: "/compose?tab=blueprint", pageId: "page-compose" },
    { from: "/study-materials", to: "/materials", pageId: "page-materials" },
    { from: "/question-library", to: "/library", pageId: "page-library" },
    { from: "/ai-generate", to: "/library?tab=generate", pageId: "page-library" },
  ] as const)("$from 重定向到 $to", async ({ from, to, pageId }) => {
    const router = buildTestRouter(from);
    render(<RouterProvider router={router} />);
    // 数据路由初次加载会执行 redirect loader 并落到目标路由，等待目标占位页出现
    await screen.findByTestId(pageId);
    expect(router.state.location.pathname + router.state.location.search).toBe(to);
  });
});
