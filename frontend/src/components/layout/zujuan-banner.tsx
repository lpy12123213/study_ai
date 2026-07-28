import { TriangleAlert, X } from "lucide-react";

import { useUiStore } from "@/stores/ui";

/** 组卷网登录态失效时的全局提示条（由 API 响应中的 login_required / cookie_expired 触发）。 */
export function ZujuanBanner() {
  const required = useUiStore((s) => s.zujuanLoginRequired);
  const dismiss = useUiStore((s) => s.setZujuanLoginRequired);
  if (!required) return null;
  return (
    <div className="flex items-center gap-3 border-b border-warning/40 bg-warning/15 px-6 py-2 text-sm text-warning-foreground dark:text-warning">
      <TriangleAlert className="size-4 shrink-0" />
      <span className="flex-1">
        组卷网登录态已失效，题源相关功能暂不可用。请在项目根目录运行
        <code className="mx-1 rounded bg-warning/20 px-1.5 py-0.5 font-mono text-xs">scripts/登录组卷网.bat</code>
        重新登录后重试。
      </span>
      <button onClick={() => dismiss(false)} className="cursor-pointer rounded-md p-1 hover:bg-warning/20" aria-label="关闭提示">
        <X className="size-4" />
      </button>
    </div>
  );
}
