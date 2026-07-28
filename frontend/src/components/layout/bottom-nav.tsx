import { NavLink } from "react-router";

import { cn } from "@/lib/utils";
import { bottomNavItems } from "@/app/router/catalog";

const ITEMS = bottomNavItems();

/** 移动端（<768px）底部主导航（规划 §5.2）：此时图标轨与上下文栏隐藏。 */
export function BottomNav() {
  return (
    <nav
      aria-label="底部主导航"
      className="fixed inset-x-0 bottom-0 z-40 flex h-16 items-stretch justify-around border-t border-border bg-background/95 backdrop-blur-md md:hidden"
    >
      {ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn(
              "flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground transition-colors",
              isActive && "text-primary",
            )
          }
        >
          <item.icon className="size-5" />
          <span className="truncate">{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
