import { useState } from "react";
import { Brain, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ThinkingBlockView } from "../model/types";
import { formatObservedDuration } from "./format";

interface ThinkingTextProps {
  thinking: ThinkingBlockView;
  /** 历史轮默认折叠；当前轮默认展开（3–5 行）。 */
  defaultExpanded?: boolean;
}

/**
 * 思考文本：只渲染后端明确下发的 user-visible thinking_delta。
 * 当前轮默认展开并限制为约 4 行，可继续展开；完成后标题显示客户端观察时长。
 */
export function ThinkingText({ thinking, defaultExpanded = true }: ThinkingTextProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [fullyOpen, setFullyOpen] = useState(false);
  const streaming = thinking.status === "streaming";

  const title = streaming
    ? "思考中…"
    : thinking.durationMs !== undefined
      ? `思考完成 · ${formatObservedDuration(thinking.durationMs)}`
      : "思考完成";

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        aria-expanded={false}
        className="mb-2 flex items-center gap-1.5 rounded-full border border-thinking-border bg-thinking-surface px-3 py-1.5 text-xs text-thinking-foreground transition-colors hover:text-foreground"
      >
        <ChevronRight className="size-3.5" />
        <Brain className="size-3.5" />
        {title}
      </button>
    );
  }

  return (
    <section
      aria-label="思考过程"
      className="mb-3 max-w-[68ch] rounded-2xl border border-thinking-border bg-thinking-surface px-4 py-3"
    >
      <button
        type="button"
        onClick={() => {
          setExpanded(false);
          setFullyOpen(false);
        }}
        aria-expanded
        className="flex w-full items-center gap-1.5 text-left text-xs font-medium text-thinking-foreground transition-colors hover:text-foreground"
      >
        <ChevronRight className="size-3.5 rotate-90 transition-transform" />
        <Brain className="size-3.5" />
        {title}
        {streaming ? (
          <span aria-hidden className="ml-1 inline-block size-1.5 animate-pulse rounded-full bg-tool-running" />
        ) : null}
      </button>
      <div
        className={cn(
          "mt-1.5 whitespace-pre-wrap text-sm leading-6 text-thinking-foreground",
          !fullyOpen && "line-clamp-4",
        )}
      >
        {thinking.text}
      </div>
      {!fullyOpen ? (
        <button
          type="button"
          onClick={() => setFullyOpen(true)}
          className="mt-1 text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
        >
          展开全部
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setFullyOpen(false)}
          className="mt-1 text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
        >
          收起
        </button>
      )}
    </section>
  );
}
