import { NavLink } from "react-router";
import { GraduationCap } from "lucide-react";

import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { navGroups } from "@/app/router/catalog";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const NAV = navGroups();

/**
 * 全局图标轨（规划 §5.1）：64px，≥768px 常驻。
 * 与上下文栏同源（navGroups 派生自 Route Catalog），仅承载图标层导航。
 */
export function IconRail() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="flex w-16 shrink-0 flex-col items-center border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="flex h-16 shrink-0 items-center justify-center">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-xs">
          <GraduationCap className="size-4.5" />
        </div>
      </div>

      <nav aria-label="主导航" className="flex min-h-0 flex-1 flex-col items-center gap-1 overflow-y-auto py-3">
        {NAV.flatMap((group) => group.items).map((item) => (
          <Tooltip key={item.to}>
            <TooltipTrigger asChild>
              <NavLink
                to={item.to}
                end={item.end}
                aria-label={item.label}
                className={({ isActive }) =>
                  cn(
                    "flex size-9 items-center justify-center rounded-lg text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                    isActive && "bg-sidebar-accent text-sidebar-accent-foreground shadow-xs",
                  )
                }
              >
                <item.icon className="size-4" />
              </NavLink>
            </TooltipTrigger>
            <TooltipContent side="right">{item.label}</TooltipContent>
          </Tooltip>
        ))}
      </nav>

      <div className="flex shrink-0 items-center justify-center border-t border-sidebar-border py-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex size-8 cursor-default items-center justify-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground">
              {(user?.username ?? "本")[0]}
            </div>
          </TooltipTrigger>
          <TooltipContent side="right">{user?.username ?? "本地用户"}</TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
}
