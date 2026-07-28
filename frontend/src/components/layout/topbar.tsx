import { useMemo } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { Activity, LogOut, Monitor, Moon, PanelLeft, Search, Settings, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { useUiStore } from "@/stores/ui";
import { useAuthStore } from "@/stores/auth";
import { useTasksStore } from "@/stores/tasks";
import { useMediaQuery } from "@/lib/use-media-query";
import { routeTitle } from "@/app/router/catalog";
import { TASK_STATUS_LABELS, TASK_TYPE_LABELS } from "@/shared/api/types";

function TaskIndicator() {
  const active = useTasksStore((s) => s.active);
  const running = useMemo(
    () =>
      Object.values(active)
        .filter((t) => ["running", "paused", "pending_review"].includes(t.status))
        .sort((a, b) => b.lastSeq - a.lastSeq),
    [active],
  );
  if (running.length === 0) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <Activity className="size-3.5 animate-pulse text-primary" />
          {running.length} 个任务
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>进行中的任务</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {running.slice(0, 6).map((t) => (
          <DropdownMenuItem key={t.taskId} asChild>
            <Link to="/tasks" className="flex flex-col items-stretch gap-1.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">
                  {t.title || TASK_TYPE_LABELS[t.type] || t.taskId}
                </span>
                <Badge variant={t.status === "pending_review" ? "warning" : "muted"} className="shrink-0">
                  {TASK_STATUS_LABELS[t.status] ?? t.status}
                </Badge>
              </div>
              <Progress value={t.progress} className="h-1" />
            </Link>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Topbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const setNavSheetOpen = useUiStore((s) => s.setNavSheetOpen);
  const setSearchOpen = useUiStore((s) => s.setSearchOpen);
  const setTheme = useUiStore((s) => s.setTheme);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const wide = useMediaQuery("(min-width: 1100px)");

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-4 backdrop-blur-md">
      <Button
        variant="ghost"
        size="icon"
        onClick={() => (wide ? toggleSidebar() : setNavSheetOpen(true))}
        aria-label="切换侧栏"
      >
        <PanelLeft className="size-4" />
      </Button>
      <h1 className="text-sm font-semibold tracking-tight">{routeTitle(location.pathname)}</h1>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={() => setSearchOpen(true)}
          className="hidden h-8 cursor-pointer items-center gap-2 rounded-md border border-input bg-card px-3 text-sm text-muted-foreground shadow-xs transition-colors hover:bg-accent hover:text-accent-foreground sm:flex"
        >
          <Search className="size-3.5" />
          全局搜索
          <kbd className="rounded border border-border bg-muted px-1 text-[10px] font-medium">⌘K</kbd>
        </button>
        <Button variant="ghost" size="icon" className="sm:hidden" onClick={() => setSearchOpen(true)} aria-label="搜索">
          <Search className="size-4" />
        </Button>

        <TaskIndicator />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="切换主题">
              <Sun className="size-4 rotate-0 scale-100 transition-transform dark:-rotate-90 dark:scale-0" />
              <Moon className="absolute size-4 rotate-90 scale-0 transition-transform dark:rotate-0 dark:scale-100" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => setTheme("light")}>
              <Sun /> 浅色
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setTheme("dark")}>
              <Moon /> 深色
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setTheme("system")}>
              <Monitor /> 跟随系统
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex size-8 cursor-pointer items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary transition-colors hover:bg-primary/20">
              {(user?.username ?? "本")[0]}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuLabel>
              <div className="text-sm font-medium text-foreground">{user?.username ?? "本地用户"}</div>
              <div className="text-xs font-normal">{user?.role === "admin" ? "管理员" : "普通用户"}</div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => navigate("/settings")}>
              <Settings /> 设置
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => {
                void logout().then(() => navigate("/login"));
              }}
            >
              <LogOut /> 退出登录
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
