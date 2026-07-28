import { NavLink } from "react-router";
import { GraduationCap } from "lucide-react";

import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { navGroups } from "@/app/router/catalog";
import { Badge } from "@/components/ui/badge";

const NAV = navGroups();

/**
 * 上下文导航栏（规划 §5.1）：208–224px，可收合。
 * 与图标轨同源（navGroups 派生自 Route Catalog），承载分组标签与文字项。
 * 在 <1100px 时以 Sheet 形式复用（由 AppShell 控制）。
 */
export function ContextBar({ className }: { className?: string }) {
  const user = useAuthStore((s) => s.user);

  return (
    <div
      className={cn(
        "flex w-52 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground",
        className,
      )}
    >
      <div className="flex h-16 shrink-0 items-center gap-2.5 border-b border-sidebar-border px-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-xs">
          <GraduationCap className="size-4.5" />
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold tracking-tight">Study AI</div>
          <div className="truncate text-[11px] text-muted-foreground">学习与出题工作台</div>
        </div>
      </div>

      <nav aria-label="分组导航" className="min-h-0 flex-1 space-y-5 overflow-y-auto px-3 py-4">
        {NAV.map((group) => (
          <div key={group.id}>
            <div className="mb-1.5 px-3 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
              {group.label}
            </div>
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                      isActive && "bg-sidebar-accent text-sidebar-accent-foreground shadow-xs",
                    )
                  }
                >
                  <item.icon className="size-4 shrink-0" />
                  <span className="truncate">{item.label}</span>
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-sidebar-border p-3">
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-1.5">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground">
            {(user?.username ?? "本")[0]}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{user?.username ?? "本地用户"}</div>
            <Badge variant={user?.role === "admin" ? "default" : "muted"} className="mt-0.5 px-1.5 text-[10px]">
              {user?.role === "admin" ? "管理员" : "用户"}
            </Badge>
          </div>
        </div>
      </div>
    </div>
  );
}
