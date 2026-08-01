import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpenText, FileStack, LibraryBig, MessagesSquare, Search } from "lucide-react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { systemApi } from "@/shared/api/system";
import type { GlobalSearchResult } from "@/shared/api/types";
import { useUiStore } from "@/stores/ui";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

const TYPE_META: Record<string, { label: string; icon: React.ComponentType<{ className?: string }> }> = {
  conversation: { label: "对话", icon: MessagesSquare },
  paper: { label: "试卷", icon: FileStack },
  study_archive: { label: "学习资料", icon: BookOpenText },
  question: { label: "题目", icon: LibraryBig },
};

const MARK_OPEN = String.fromCharCode(1);
const MARK_CLOSE = String.fromCharCode(2);
const SEARCH_DEBOUNCE_MS = 80;
const SEARCH_CACHE_MS = 30_000;

/** 后端 snippet 用 \u0001/\u0002 包裹高亮词，转成 <mark>。 */
function HighlightedSnippet({ text }: { text: string }) {
  const html = useMemo(() => {
    const escaped = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    return escaped.split(MARK_OPEN).join("<mark>").split(MARK_CLOSE).join("</mark>");
  }, [text]);
  // 控制字符已被替换为安全标签，其余内容已转义
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

function resultLink(r: GlobalSearchResult): string | null {
  switch (r.type) {
    case "conversation":
      if (!r.conversation_id) return null;
      // 有最佳命中消息时带 message 锚点，聊天页定位到该条消息
      return r.message_id ? `/chat/${r.conversation_id}?message=${r.message_id}` : `/chat/${r.conversation_id}`;
    case "paper":
      if (!r.paper_id) return null;
      // 有最佳命中题目时带 question 锚点，试卷页定位到该题
      return r.question_id ? `/papers/${r.paper_id}?question=${encodeURIComponent(r.question_id)}` : `/papers/${r.paper_id}`;
    case "study_archive":
      return r.archive_id ? `/materials/${r.archive_id}` : null;
    case "question":
      return r.question_id ? `/library?q=${encodeURIComponent(r.question_id)}` : null;
    default:
      return null;
  }
}

export function GlobalSearch() {
  const open = useUiStore((s) => s.searchOpen);
  const setOpen = useUiStore((s) => s.setSearchOpen);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    if (open) {
      setQ("");
      setDebounced("");
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const { data, isFetching } = useQuery({
    queryKey: ["global-search", debounced],
    queryFn: ({ signal }) => systemApi.search(debounced, undefined, 30, signal),
    enabled: open && debounced.length > 0,
    staleTime: SEARCH_CACHE_MS,
  });

  const results = data?.results ?? [];

  const go = (r: GlobalSearchResult) => {
    const link = resultLink(r);
    if (!link) return;
    setOpen(false);
    navigate(link);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="top-[20%] max-w-xl translate-y-0 gap-0 overflow-hidden p-0" aria-describedby={undefined}>
        <div className="flex items-center gap-2 border-b border-border px-4">
          {isFetching ? <Spinner className="size-4" /> : <Search className="size-4 text-muted-foreground" />}
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索对话、试卷、资料、题目…"
            className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">ESC</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto p-2">
          {debounced.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">输入关键词开始搜索</div>
          ) : results.length === 0 && !isFetching ? (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">没有找到与「{debounced}」相关的内容</div>
          ) : (
            results.map((r, i) => {
              const meta = TYPE_META[r.type] ?? { label: r.type, icon: Search };
              const link = resultLink(r);
              return (
                <button
                  key={`${r.type}-${i}`}
                  onClick={() => go(r)}
                  disabled={!link}
                  className={cn(
                    "flex w-full cursor-pointer items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
                    link ? "hover:bg-accent" : "opacity-60",
                  )}
                >
                  <meta.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium">{r.title || "未命名"}</span>
                      <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{meta.label}</span>
                      {typeof r.match_count === "number" && r.match_count > 1 ? (
                        <span className="shrink-0 rounded bg-accent px-1.5 py-0.5 text-[10px] text-accent-foreground">
                          {r.match_count} 条匹配
                        </span>
                      ) : null}
                    </span>
                    {r.snippet ? (
                      <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
                        <HighlightedSnippet text={r.snippet} />
                      </span>
                    ) : null}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
