import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import {
  FileText,
  LayoutDashboard,
  Layers,
  MessagesSquare,
  PenTool,
  Settings,
  ChevronLeft,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/shared/ThemeToggle";
import { motion, AnimatePresence } from "framer-motion";

const sidebarItems = [
  {
    title: "概览",
    href: "/dashboard",
    icon: LayoutDashboard,
  },
  {
    title: "蓝图组卷",
    href: "/blueprint",
    icon: Layers,
  },
  {
    title: "AI 对话",
    href: "/chat",
    icon: MessagesSquare,
  },
  {
    title: "画布对话",
    href: "/flow",
    icon: PenTool,
  },
  {
    title: "试卷",
    href: "/papers",
    icon: FileText,
  },
  {
    title: "设置",
    href: "/settings",
    icon: Settings,
  },
];

export function Sidebar() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <motion.div
      initial={{ width: 256 }}
      animate={{ width: collapsed ? 80 : 256 }}
      transition={{ duration: 0.3, ease: "easeInOut" }}
      className="relative flex h-full flex-col border-r bg-card shadow-sm z-10"
    >
      <div className="flex items-center justify-between p-4">
        <div className={cn("flex items-center gap-2 overflow-hidden", collapsed && "justify-center")}>
           <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
             <Sparkles className="h-5 w-5" />
           </div>
           <AnimatePresence>
            {!collapsed && (
              <motion.div
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "auto" }}
                exit={{ opacity: 0, width: 0 }}
                className="whitespace-nowrap font-bold"
              >
                组卷助手
              </motion.div>
            )}
           </AnimatePresence>
        </div>
      </div>

      <nav className="flex-1 space-y-2 p-2">
        {sidebarItems.map((item) => {
          const isActive =
            location.pathname === item.href ||
            location.pathname.startsWith(`${item.href}/`);
          return (
            <Link key={item.href} to={item.href}>
              <Button
                variant={isActive ? "secondary" : "ghost"}
                className={cn(
                  "relative w-full justify-start overflow-hidden",
                  collapsed ? "px-0 justify-center" : "px-4",
                  isActive && "bg-secondary/80 font-medium shadow-sm"
                )}
                title={collapsed ? item.title : undefined}
              >
                {isActive && (
                  <motion.div
                    layoutId="active-pill"
                    className="absolute inset-0 border-l-2 border-primary bg-primary/5"
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                  />
                )}
                <item.icon className={cn("h-5 w-5 shrink-0 transition-transform", isActive && "scale-110 text-primary")} />
                {!collapsed && (
                    <motion.span
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.1 }}
                        className="ml-3 truncate"
                    >
                        {item.title}
                    </motion.span>
                )}
              </Button>
            </Link>
          );
        })}
      </nav>

      <div className="p-2 border-t space-y-2">
        <div className={cn("flex items-center", collapsed ? "justify-center" : "justify-between px-2")}>
             <ThemeToggle />
             {!collapsed && <span className="text-xs text-muted-foreground">v1.0.0</span>}
        </div>
        <Button
            variant="ghost"
            size="sm"
            className="w-full justify-center text-muted-foreground hover:text-foreground"
            onClick={() => setCollapsed(!collapsed)}
        >
             {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </Button>
      </div>
    </motion.div>
  );
}
