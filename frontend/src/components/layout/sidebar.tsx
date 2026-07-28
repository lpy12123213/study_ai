import { useUiStore } from "@/stores/ui";
import { useMediaQuery } from "@/lib/use-media-query";
import { IconRail } from "@/components/layout/icon-rail";
import { ContextBar } from "@/components/layout/context-bar";

/**
 * 桌面侧栏（≥768px）：64px 图标轨 + 208px 上下文栏（规划 §5.1/§5.2）。
 * - ≥1440px：图标轨 + 上下文栏；
 * - 1100–1439px：上下文栏默认收合（首次访问由 AppShell 置位），可手动展开；
 * - 768–1099px：仅图标轨，上下文经顶栏按钮以 Sheet 打开；
 * - <768px：整体隐藏，由 BottomNav 接管导航。
 */
export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const wide = useMediaQuery("(min-width: 1100px)");

  return (
    <aside className="sticky top-0 hidden h-screen shrink-0 md:flex">
      <IconRail />
      {wide && !collapsed ? <ContextBar /> : null}
    </aside>
  );
}
