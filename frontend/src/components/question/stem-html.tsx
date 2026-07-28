import { useMemo } from "react";

import { rewriteStemHtml } from "@/lib/media";
import { cn } from "@/lib/utils";

/**
 * 题干渲染。后端返回的 stem/stem_html 已消毒；其中第三方图片统一改写为
 * /api/media/proxy?url= 加载。
 */
export function StemHtml({ html, className }: { html?: string | null; className?: string }) {
  const safe = useMemo(() => rewriteStemHtml(html), [html]);
  if (!safe) return null;
  // 内容来自后端已消毒的题干 HTML；图片已改写为本地代理
  return <div className={cn("markdown-body stem-html", className)} dangerouslySetInnerHTML={{ __html: safe }} />;
}
