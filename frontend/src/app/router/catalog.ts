/**
 * Route Catalog（架构 Phase 1）：路由、侧栏导航、顶栏标题的单一真源。
 *
 * - router.tsx 由 APP_ROUTES + 页面组件映射派生路由对象；
 * - sidebar.tsx 由 navGroups() 派生导航分组；
 * - topbar.tsx 由 routeTitle() 解析当前页标题。
 * 新增页面时只需在此登记一条 AppRouteMeta 并在 router.tsx 挂组件。
 */
import { matchPath } from "react-router";
import {
  BookOpenText,
  FileStack,
  LayoutDashboard,
  LibraryBig,
  ListTodo,
  MessagesSquare,
  Settings,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

export type NavGroupId = "overview" | "create" | "resources" | "system";

/** 主工作区内容模式（规划 §5.1）：决定 shell 的滚动所有权与宽度约束。 */
export type ContentMode = "document" | "workspace" | "conversation";

export interface AppRouteMeta {
  id: string;
  /** react-router 路径模式（与 router.tsx 中一致）。 */
  path: string;
  /** 顶栏标题。 */
  title: string;
  /** shell = 带侧栏/顶栏的主框架；public = 无框架公开页。 */
  layout: "shell" | "public";
  /** 内容模式；缺省 document（页面滚动、内容居中限宽）。 */
  contentMode?: ContentMode;
  /** 侧栏导航项；缺省表示不出现在导航中（如详情页）。 */
  nav?: {
    group: NavGroupId;
    label: string;
    icon: LucideIcon;
    /** NavLink end 匹配（仅根路径需要）。 */
    end?: boolean;
    order: number;
  };
}

export const NAV_GROUPS: { id: NavGroupId; label: string }[] = [
  { id: "overview", label: "总览" },
  { id: "create", label: "创作" },
  { id: "resources", label: "资源" },
  { id: "system", label: "系统" },
];

export const APP_ROUTES: AppRouteMeta[] = [
  { id: "login", path: "/login", title: "登录", layout: "public" },
  { id: "share", path: "/share/:token", title: "分享", layout: "public" },

  {
    id: "home",
    path: "/",
    title: "工作台",
    layout: "shell",
    nav: { group: "overview", label: "工作台", icon: LayoutDashboard, end: true, order: 1 },
  },
  {
    id: "chat",
    path: "/chat",
    title: "对话",
    layout: "shell",
    contentMode: "conversation",
    nav: { group: "create", label: "对话", icon: MessagesSquare, order: 1 },
  },
  { id: "chat-detail", path: "/chat/:id", title: "对话", layout: "shell", contentMode: "conversation" },
  {
    id: "compose",
    path: "/compose",
    title: "组卷工作室",
    layout: "shell",
    contentMode: "workspace",
    nav: { group: "create", label: "组卷", icon: FileStack, order: 2 },
  },
  {
    id: "materials",
    path: "/materials",
    title: "学习资料",
    layout: "shell",
    contentMode: "conversation",
    nav: { group: "create", label: "学习资料", icon: BookOpenText, order: 3 },
  },
  { id: "materials-detail", path: "/materials/:id", title: "资料详情", layout: "shell", contentMode: "workspace" },
  {
    id: "deepthink",
    path: "/deepthink",
    title: "DeepThink 深度解题",
    layout: "shell",
    nav: { group: "create", label: "DeepThink", icon: Sparkles, order: 4 },
  },
  {
    id: "papers",
    path: "/papers",
    title: "试卷库",
    layout: "shell",
    contentMode: "workspace",
    nav: { group: "resources", label: "试卷库", icon: FileStack, order: 1 },
  },
  { id: "paper-detail", path: "/papers/:id", title: "试卷详情", layout: "shell", contentMode: "workspace" },
  {
    id: "library",
    path: "/library",
    title: "题库",
    layout: "shell",
    contentMode: "workspace",
    nav: { group: "resources", label: "题库", icon: LibraryBig, order: 2 },
  },
  {
    id: "tasks",
    path: "/tasks",
    title: "任务中心",
    layout: "shell",
    contentMode: "workspace",
    nav: { group: "system", label: "任务中心", icon: ListTodo, order: 1 },
  },
  {
    id: "settings",
    path: "/settings",
    title: "设置",
    layout: "shell",
    nav: { group: "system", label: "设置", icon: Settings, order: 2 },
  },
];

/**
 * 兼容重定向（F11）：旧指南入口 / 旧书签 → 当前路由。
 * 独立于 APP_ROUTES 存在，避免污染侧栏导航；由 router.tsx 派生成顶层 redirect 路由。
 */
export interface RouteRedirect {
  /** 匹配的旧路径（精确）。 */
  from: string;
  /** 跳转目标；query 直接写在 to 中（如 /library?tab=generate）。 */
  to: string;
}

export const REDIRECTS: RouteRedirect[] = [
  { from: "/blueprint", to: "/compose?tab=blueprint" },
  { from: "/study-materials", to: "/materials" },
  { from: "/question-library", to: "/library" },
  { from: "/ai-generate", to: "/library?tab=generate" },
];

export interface NavItemView {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

export interface NavGroupView {
  id: NavGroupId;
  label: string;
  items: NavItemView[];
}

/** 侧栏导航分组（按 NAV_GROUPS 顺序，组内按 order 排序）。 */
export function navGroups(): NavGroupView[] {
  return NAV_GROUPS.map((group) => ({
    id: group.id,
    label: group.label,
    items: APP_ROUTES.filter((r) => r.nav?.group === group.id)
      .sort((a, b) => a.nav!.order - b.nav!.order)
      .map((r) => ({ to: r.path, label: r.nav!.label, icon: r.nav!.icon, end: r.nav!.end })),
  })).filter((group) => group.items.length > 0);
}

/** 顶栏标题：按路径模式精确匹配（matchPath 默认 end 匹配），未命中回退产品名。 */
export function routeTitle(pathname: string): string {
  for (const route of APP_ROUTES) {
    if (route.layout !== "shell") continue;
    if (matchPath({ path: route.path, end: true }, pathname)) return route.title;
  }
  return "Study AI";
}

/** 内容模式：与 routeTitle 同一匹配规则，未命中按 document。 */
export function contentModeForPath(pathname: string): ContentMode {
  for (const route of APP_ROUTES) {
    if (route.layout !== "shell") continue;
    if (matchPath({ path: route.path, end: true }, pathname)) return route.contentMode ?? "document";
  }
  return "document";
}

/** 移动端底部主导航（<768px）：高频目的地，顺序即展示顺序。 */
export const BOTTOM_NAV_IDS = ["home", "chat", "compose", "library", "settings"] as const;

export function bottomNavItems(): NavItemView[] {
  return BOTTOM_NAV_IDS.map((id) => {
    const route = APP_ROUTES.find((r) => r.id === id);
    if (!route?.nav) throw new Error(`底部导航引用了无 nav 的路由: ${id}`);
    return { to: route.path, label: route.nav.label, icon: route.nav.icon, end: route.nav.end };
  });
}
