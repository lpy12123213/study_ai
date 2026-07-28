import { isRouteErrorResponse, useNavigate, useRouteError } from "react-router";
import { AlertTriangle, Home, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * 路由级 error boundary（架构 Phase 2）。
 * 挂在每个业务路由上：页面渲染/懒加载失败时 shell 与导航保持可用，
 * 只有内容区降级为错误说明 + 恢复操作。
 */
export function RouteErrorBoundary() {
  const error = useRouteError();
  const navigate = useNavigate();

  let title = "页面出现错误";
  let description = "渲染此页面时发生了意外错误，可以重试或返回工作台。";
  if (isRouteErrorResponse(error)) {
    title = `请求失败（${error.status}）`;
    description = error.statusText || description;
  } else if (error instanceof Error) {
    // 懒加载 chunk 拉取失败（部署更新后旧 chunk 404）最常见，提示刷新
    if (/Failed to fetch dynamically imported module|Importing a module script failed/i.test(error.message)) {
      title = "页面资源已更新";
      description = "应用发布了新版本，刷新页面即可加载最新资源。";
    } else {
      description = error.message || description;
    }
  }

  return (
    <div className="flex h-full min-h-[50dvh] items-center justify-center p-6">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-6 text-center shadow-soft">
        <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <AlertTriangle className="size-5" />
        </div>
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        <p className="mt-1.5 break-words text-sm text-muted-foreground">{description}</p>
        <div className="mt-4 flex items-center justify-center gap-2">
          <Button variant="outline" onClick={() => window.location.reload()}>
            <RotateCw />
            刷新页面
          </Button>
          <Button onClick={() => void navigate("/")}>
            <Home />
            返回工作台
          </Button>
        </div>
      </div>
    </div>
  );
}
