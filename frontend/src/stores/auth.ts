import { create } from "zustand";

import { apiFetch } from "@/shared/api/http-client";
import type { LoginResponse, UserInfo } from "@/shared/api/types";

interface AuthState {
  user: UserInfo | null;
  bootstrapped: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  bootstrap: () => Promise<void>;
  setUser: (user: UserInfo | null) => void;
  clear: () => void;
}

/**
 * 会话由后端 HttpOnly cookie 维持（apiFetch 走 credentials: "same-origin" 自动携带）。
 * 前端不在 JS/localStorage 中保存访问令牌，避免 XSS 窃取。
 */
export const useAuthStore = create<AuthState>()((set, get) => ({
  user: null,
  bootstrapped: false,

  async login(username, password) {
    const res = await apiFetch<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: { username, password },
      silent: true,
    });
    set({ user: res.user, bootstrapped: true });
  },

  async logout() {
    try {
      await apiFetch("/api/auth/logout", { method: "POST", silent: true });
    } catch {
      // 本地模式下登出接口可能失败，忽略
    }
    set({ user: null });
  },

  async bootstrap() {
    if (get().bootstrapped) return;
    try {
      const user = await apiFetch<UserInfo>("/api/auth/me", { silent: true });
      set({ user, bootstrapped: true });
    } catch {
      set({ user: null, bootstrapped: true });
    }
  },

  setUser: (user) => set({ user }),
  clear: () => set({ user: null }),
}));
