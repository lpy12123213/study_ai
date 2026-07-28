import { useEffect } from "react";
import { Outlet, useLocation } from "react-router";
import { GraduationCap } from "lucide-react";

import { Toaster } from "@/components/ui/toaster";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { ZujuanBanner } from "@/components/layout/zujuan-banner";
import { GlobalSearch } from "@/components/layout/global-search";
import { BottomNav } from "@/components/layout/bottom-nav";
import { ContextBar } from "@/components/layout/context-bar";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { applyTheme, useUiStore } from "@/stores/ui";
import { useAuthStore } from "@/stores/auth";
import { useMediaQuery } from "@/lib/use-media-query";
import { contentModeForPath } from "@/app/router/catalog";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

export function AppShell() {
  const location = useLocation();
  const theme = useUiStore((s) => s.theme);
  const setSearchOpen = useUiStore((s) => s.setSearchOpen);
  const setSidebarCollapsed = useUiStore((s) => s.setSidebarCollapsed);
  const navSheetOpen = useUiStore((s) => s.navSheetOpen);
  const setNavSheetOpen = useUiStore((s) => s.setNavSheetOpen);
  const bootstrapped = useAuthStore((s) => s.bootstrapped);
  const bootstrap = useAuthStore((s) => s.bootstrap);
  const wide = useMediaQuery("(min-width: 1100px)");

  const mode = contentModeForPath(location.pathname);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  // 首次访问且视口 <1440px 时默认收合上下文栏（§5.2：1100–1439 默认收合）
  useEffect(() => {
    try {
      if (localStorage.getItem("study-ai-ui") == null && window.innerWidth < 1440) {
        setSidebarCollapsed(true);
      }
    } catch {
      // localStorage 不可用时保持默认展开
    }
  }, [setSidebarCollapsed]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setSearchOpen]);

  // 路由变化时关闭小屏导航 Sheet
  useEffect(() => {
    setNavSheetOpen(false);
  }, [location.pathname, setNavSheetOpen]);

  if (!bootstrapped) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background">
        <div className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-lift">
          <GraduationCap className="size-6" />
        </div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner /> Study AI 正在启动…
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar />
      <div
        className={cn(
          "flex min-w-0 flex-1 flex-col",
          // conversation 模式：shell 自身不滚动，滚动所有权交给消息区（§5.1）
          mode === "conversation" && "h-dvh overflow-hidden",
        )}
      >
        <Topbar />
        <ZujuanBanner />
        {mode === "conversation" ? (
          <main className="flex min-h-0 flex-1 flex-col overflow-hidden pb-16 md:pb-0">
            <Outlet />
          </main>
        ) : (
          <main className="min-w-0 flex-1 px-6 py-6 pb-20 md:pb-6 lg:px-8">
            <div className={cn(mode === "document" && "mx-auto w-full max-w-[1480px]")}>
              <Outlet />
            </div>
          </main>
        )}
      </div>
      <Toaster />
      <GlobalSearch />
      <BottomNav />

      {/* 小屏（<1100px）上下文导航 Sheet */}
      <Sheet open={navSheetOpen && !wide} onOpenChange={setNavSheetOpen}>
        <SheetContent side="left" className="w-72 p-0" aria-label="导航">
          <SheetHeader className="sr-only">
            <SheetTitle>导航</SheetTitle>
            <SheetDescription>站点分组导航</SheetDescription>
          </SheetHeader>
          <ContextBar className="h-full w-full border-r-0" />
        </SheetContent>
      </Sheet>
    </div>
  );
}
