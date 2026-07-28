import { create } from "zustand";
import { persist } from "zustand/middleware";

import { apiFetch } from "@/shared/api/http-client";
import type { LoginResponse, UserInfo } from "@/shared/api/types";

interface AuthState {
  token: string | null;
  user: UserInfo | null;
  bootstrapped: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  bootstrap: () => Promise<void>;
  setUser: (user: UserInfo | null) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      bootstrapped: false,

      async login(username, password) {
        const res = await apiFetch<LoginResponse>("/api/auth/login", {
          method: "POST",
          body: { username, password },
          silent: true,
        });
        set({ token: res.access_token, user: res.user, bootstrapped: true });
      },

      async logout() {
        try {
          await apiFetch("/api/auth/logout", { method: "POST", silent: true });
        } catch {
          // 本地模式下登出接口可能失败，忽略
        }
        set({ token: null, user: null });
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
      clear: () => set({ token: null, user: null }),
    }),
    {
      name: "study-ai-auth",
      partialize: (s) => ({ token: s.token }),
    },
  ),
);
