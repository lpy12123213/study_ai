import { useLayoutEffect, useMemo, useRef } from "react";
import renderMathInElement from "katex/contrib/auto-render";

import { rewriteStemHtml } from "@/lib/media";
import { cn } from "@/lib/utils";

const LATEX_DELIMITERS = [
  { left: "$$", right: "$$", display: true },
  { left: "\\[", right: "\\]", display: true },
  { left: "\\(", right: "\\)", display: false },
  { left: "$", right: "$", display: false },
] as const;

/**
 * 题目内容渲染。后端返回的题干/答案/解析 HTML 已消毒；其中第三方图片统一
 * 改写为 /api/media/proxy?url= 加载，常见 TeX 分隔符由 KaTeX 自动渲染。
 */
export function StemHtml({ html, className }: { html?: string | null; className?: string }) {
  const safe = useMemo(() => rewriteStemHtml(html), [html]);
  const containerRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container || !safe) return;

    renderMathInElement(container, {
      delimiters: LATEX_DELIMITERS,
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      ignoredClasses: ["katex", "katex-display"],
      throwOnError: false,
      strict: "ignore",
      trust: false,
      errorCallback: () => undefined,
    });
  }, [safe]);

  if (!safe) return null;
  // 内容来自后端已消毒的题干 HTML；图片已改写为本地代理
  return (
    <div
      ref={containerRef}
      className={cn("markdown-body stem-html", className)}
      dangerouslySetInnerHTML={{ __html: safe }}
    />
  );
}
