import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "light" | "dark" | "system";

export interface ToastItem {
  id: number;
  title: string;
  description?: string;
  variant?: "default" | "success" | "destructive" | "warning";
  duration?: number;
}

interface UiState {
  theme: Theme;
  setTheme: (t: Theme) => void;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (v: boolean) => void;
  /** 小屏（<1100px）导航 Sheet 开关：上下文栏以覆盖式 Sheet 展开 */
  navSheetOpen: boolean;
  setNavSheetOpen: (v: boolean) => void;
  toasts: ToastItem[];
  toast: (t: Omit<ToastItem, "id">) => number;
  dismissToast: (id: number) => void;
  /** 组卷网登录态失效标记（来自 API 响应的 login_required / cookie_expired） */
  zujuanLoginRequired: boolean;
  setZujuanLoginRequired: (v: boolean) => void;
  searchOpen: boolean;
  setSearchOpen: (v: boolean) => void;
}

let toastSeq = 1;

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      setTheme: (theme) => set({ theme }),

      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),

      navSheetOpen: false,
      setNavSheetOpen: (v) => set({ navSheetOpen: v }),

      toasts: [],
      toast: (t) => {
        const id = toastSeq++;
        set((s) => ({ toasts: [...s.toasts.slice(-4), { ...t, id }] }));
        const duration = t.duration ?? 4000;
        if (duration > 0) {
          setTimeout(() => {
            set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) }));
          }, duration);
        }
        return id;
      },
      dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),

      zujuanLoginRequired: false,
      setZujuanLoginRequired: (v) => set({ zujuanLoginRequired: v }),

      searchOpen: false,
      setSearchOpen: (v) => set({ searchOpen: v }),
    }),
    {
      name: "study-ai-ui",
      partialize: (s) => ({ theme: s.theme, sidebarCollapsed: s.sidebarCollapsed }),
    },
  ),
);

/** 应用主题到 <html>。system 时跟随 prefers-color-scheme。 */
export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  const dark =
    theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
}
