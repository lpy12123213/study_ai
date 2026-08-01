/**
 * app 层 HTTP 观察者接线（架构 Phase 1）。
 *
 * shared/api 的纯 client 不感知 store；这里把组卷网登录态检查、429 限流提示
 * 接到对应 store。鉴权依赖 HttpOnly cookie（credentials: "same-origin"），
 * 不注入 Bearer 令牌。应用启动时调用一次 registerHttpObservers()。
 */
import { configureHttpClient } from "@/shared/api/http-client";
import { resolveApiBaseUrl } from "@/shared/api/config";
import { useUiStore } from "@/stores/ui";

/** 成功或失败响应里都可能携带组卷网登录态标记。 */
function inspectZujuanPayload(payload: unknown) {
  if (payload && typeof payload === "object") {
    const p = payload as { login_required?: unknown; cookie_expired?: unknown };
    if (p.login_required === true || p.cookie_expired === true) {
      useUiStore.getState().setZujuanLoginRequired(true);
    }
  }
}

export function registerHttpObservers(): void {
  configureHttpClient({
    baseUrl: resolveApiBaseUrl(),
    onPayload: inspectZujuanPayload,
    onError: (error, { silent }) => {
      if (error.status === 429 && !silent) {
        useUiStore.getState().toast({
          title: error.code === "login_locked" ? "登录已锁定" : "请求过于频繁",
          description: error.code === "login_locked" ? "失败次数过多，请稍后再试" : "已触发限流，请稍后再试",
          variant: "warning",
        });
      }
    },
  });
}
