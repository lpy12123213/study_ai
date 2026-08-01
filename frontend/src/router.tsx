import { createBrowserRouter, redirect, type RouteObject } from "react-router";
import type { ComponentType } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { NotFoundPage } from "@/pages/not-found";
import { APP_ROUTES, REDIRECTS } from "@/app/router/catalog";
import { RouteErrorBoundary } from "@/app/router/route-error-boundary";

/**
 * catalog 路由 id → 页面懒加载器（架构 Phase 2）。
 * 业务页面不再同步进入主包；Vite 按此拆分领域 chunk。
 */
const PAGE_LOADERS: Record<string, () => Promise<{ Component: ComponentType }>> = {
  login: () => import("@/pages/auth/login").then((m) => ({ Component: m.LoginPage })),
  share: () => import("@/pages/share").then((m) => ({ Component: m.SharePage })),
  home: () => import("@/pages/home").then((m) => ({ Component: m.HomePage })),
  chat: () => import("@/pages/chat").then((m) => ({ Component: m.ChatPage })),
  "chat-detail": () => import("@/pages/chat").then((m) => ({ Component: m.ChatPage })),
  compose: () => import("@/pages/compose").then((m) => ({ Component: m.ComposePage })),
  papers: () => import("@/pages/papers").then((m) => ({ Component: m.PapersPage })),
  "paper-detail": () => import("@/pages/papers/detail").then((m) => ({ Component: m.PaperDetailPage })),
  library: () => import("@/pages/library").then((m) => ({ Component: m.LibraryPage })),
  materials: () => import("@/pages/materials").then((m) => ({ Component: m.MaterialsPage })),
  "materials-detail": () =>
    import("@/pages/materials/archive-detail").then((m) => ({ Component: m.ArchiveDetailPage })),
  deepthink: () => import("@/pages/deepthink").then((m) => ({ Component: m.DeepthinkPage })),
  tasks: () => import("@/pages/tasks").then((m) => ({ Component: m.TasksPage })),
  settings: () => import("@/pages/settings").then((m) => ({ Component: m.SettingsPage })),
};

function toRoute(meta: (typeof APP_ROUTES)[number]): RouteObject {
  const load = PAGE_LOADERS[meta.id];
  if (!load) throw new Error(`route "${meta.id}" 缺少页面加载器映射`);
  return { path: meta.path, lazy: load, errorElement: <RouteErrorBoundary /> };
}

const shellChildren: RouteObject[] = APP_ROUTES.filter((r) => r.layout === "shell").map(toRoute);

/** 兼容重定向（F11）：精确匹配 from，loader 返回 redirect 到 to。 */
const redirectRoutes: RouteObject[] = REDIRECTS.map((r) => ({
  path: r.from,
  loader: () => redirect(r.to),
}));

/** 初次进入时懒加载页面模块期间的极简占位（避免空白闪屏）。 */
const bootFallback = (
  <div className="flex h-dvh items-center justify-center bg-background">
    <div className="size-6 animate-spin rounded-full border-2 border-border border-t-primary" aria-label="加载中" />
  </div>
);

export const router = createBrowserRouter([
  {
    hydrateFallbackElement: bootFallback,
    errorElement: <RouteErrorBoundary />,
    children: [
      ...APP_ROUTES.filter((r) => r.layout === "public").map(toRoute),
      // redirect 路由必须在 AppShell 之前：精确路径优先于 AppShell 内的 '*' 兜底
      ...redirectRoutes,
      {
        element: <AppShell />,
        errorElement: <RouteErrorBoundary />,
        children: [...shellChildren, { path: "*", element: <NotFoundPage /> }],
      },
    ],
  },
]);
