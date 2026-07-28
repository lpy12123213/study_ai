import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ExternalLink,
  FileStack,
  Plus,
  Search,
  SearchX,
  Trash2,
  TriangleAlert,
} from "lucide-react";

import { ApiError } from "@/shared/api/http-client";
import { papersApi } from "@/features/paper-library/api";
import type { PaperSummary } from "@/shared/api/types";
import { formatDateTime } from "@/lib/format";
import { parseIntParam, parseStringParam, updateSearchParams } from "@/shared/lib/search-params";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

/**
 * 试卷库 · Library Master-Detail（视觉规划 §5.3）。
 * - 左列：高密度试卷列表（小圆角、行式），搜索词与选中项均入 URL（?q= / ?selected=）；
 * - 右列（≥1024px）：选中试卷的主从详情预览；窄屏点击直接进入 /papers/:id 详情页；
 * - 不把每条记录做成大号营销卡片。
 */

function PaperRow({
  paper,
  active,
  onOpen,
  onDelete,
}: {
  paper: PaperSummary;
  active: boolean;
  onOpen: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      className={cn(
        "group flex items-center gap-3 border-b border-border px-3 py-2.5 transition-colors last:border-b-0",
        active ? "bg-accent text-accent-foreground" : "hover:bg-muted/60",
      )}
    >
      <button type="button" onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-3 text-left">
        <FileStack className={cn("size-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium" title={paper.paper_name}>
            {paper.paper_name}
          </span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            {paper.question_count} 题 · {formatDateTime(paper.created_at)}
          </span>
        </span>
      </button>
      <button
        type="button"
        aria-label={`删除试卷 ${paper.paper_name}`}
        onClick={onDelete}
        className="shrink-0 rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100 hover:bg-background hover:text-destructive"
      >
        <Trash2 className="size-3.5" />
      </button>
    </div>
  );
}

/** 右侧详情预览：题目清单 + 完整页入口（分析/导出在完整页）。 */
function PaperPreviewPanel({ paperId }: { paperId: number }) {
  const query = useQuery({
    queryKey: ["papers", "detail", paperId],
    queryFn: () => papersApi.get(paperId),
  });

  if (query.isPending) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }
  if (query.isError) {
    return (
      <EmptyState
        icon={TriangleAlert}
        title="详情加载失败"
        description={query.error instanceof ApiError ? query.error.message : "网络异常，请稍后重试"}
      />
    );
  }
  const data = query.data;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold" title={data.paper_name}>
            {data.paper_name}
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {data.questions.length} 题 · 创建于 {formatDateTime(data.created_at)}
          </p>
        </div>
        <Button asChild size="sm" variant="outline">
          <Link to={`/papers/${paperId}`}>
            <ExternalLink />
            打开完整页（分析 / 导出）
          </Link>
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <ol className="space-y-2">
          {data.questions.map((q, i) => (
            <li key={q.question_id} className="rounded-md border border-border bg-surface px-3 py-2">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="font-mono">{q.order ?? i + 1}.</span>
                {q.type ? <Badge variant="secondary">{q.type}</Badge> : null}
                {q.difficulty ? <Badge variant="outline">{q.difficulty}</Badge> : null}
                {q.knowledge_point ? <span className="truncate">{q.knowledge_point}</span> : null}
              </div>
              {q.stem ? (
                <p className="mt-1 line-clamp-2 text-sm text-foreground/90">{q.stem}</p>
              ) : (
                <p className="mt-1 text-xs text-muted-foreground">题干见完整页（ID: {q.question_id}）</p>
              )}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

export function PaperLibraryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);
  const isDesktop = useMediaQuery("(min-width: 1024px)");

  const [searchParams, setSearchParams] = useSearchParams();
  const keyword = parseStringParam(searchParams, "q") ?? "";
  const selectedId = parseIntParam(searchParams, "selected", { min: 1 });
  const [pendingDelete, setPendingDelete] = useState<PaperSummary | null>(null);

  const patchParams = (patch: Record<string, string | number | null | undefined>, replace = true) =>
    setSearchParams((prev) => updateSearchParams(prev, patch), { replace });

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["papers"],
    queryFn: () => papersApi.list(100),
  });

  const deleteMutation = useMutation({
    mutationFn: (paperId: number) => papersApi.remove(paperId),
    onSuccess: (_data, paperId) => {
      toast({ title: "试卷已删除", variant: "success" });
      setPendingDelete(null);
      if (paperId === selectedId) patchParams({ selected: null });
      void queryClient.invalidateQueries({ queryKey: ["papers"] });
    },
    onError: (err) => {
      toast({
        title: "删除失败",
        description: err instanceof ApiError ? err.message : "网络异常，请稍后重试",
        variant: "destructive",
      });
    },
  });

  const papers = useMemo(() => data ?? [], [data]);
  const kw = keyword.trim().toLowerCase();
  const filtered = useMemo(
    () => (kw ? papers.filter((p) => p.paper_name.toLowerCase().includes(kw)) : papers),
    [papers, kw],
  );

  const openPaper = (paper: PaperSummary) => {
    if (isDesktop) {
      // 选中项入 URL（可分享/可恢复）；选择产生历史条目，返回键可回上一个选中
      patchParams({ selected: paper.paper_id }, false);
    } else {
      void navigate(`/papers/${paper.paper_id}`);
    }
  };

  return (
    <div className="flex h-full min-h-0 animate-fade-in gap-4 p-4">
      {/* 左列：搜索 + 高密度列表 */}
      <section
        aria-label="试卷列表"
        className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-xl border border-border bg-card shadow-soft lg:w-[380px] lg:shrink-0"
      >
        <div className="shrink-0 space-y-2.5 border-b border-border p-3">
          <div className="flex items-center justify-between gap-2">
            <h1 className="text-base font-semibold tracking-tight">试卷库</h1>
            <Button asChild size="sm">
              <Link to="/compose">
                <Plus />
                去组卷
              </Link>
            </Button>
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={(e) => patchParams({ q: e.target.value })}
              placeholder="搜索试卷名称…"
              aria-label="搜索试卷"
              className="pl-9"
            />
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {isPending ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : isError ? (
            <EmptyState
              icon={TriangleAlert}
              title="试卷加载失败"
              description={error instanceof ApiError ? error.message : "网络异常，请确认后端服务已启动"}
              action={
                <Button variant="outline" onClick={() => void refetch()}>
                  重试
                </Button>
              }
            />
          ) : filtered.length === 0 ? (
            papers.length === 0 ? (
              <EmptyState
                icon={FileStack}
                title="还没有试卷"
                description="从蓝图组卷或整卷生成开始，创建你的第一份试卷"
              />
            ) : (
              <EmptyState
                icon={SearchX}
                title="没有匹配的试卷"
                description={`没有找到名称包含“${keyword.trim()}”的试卷`}
                action={
                  <Button variant="outline" onClick={() => patchParams({ q: null })}>
                    清除搜索
                  </Button>
                }
              />
            )
          ) : (
            <div role="list">
              {filtered.map((paper) => (
                <PaperRow
                  key={paper.paper_id}
                  paper={paper}
                  active={paper.paper_id === selectedId}
                  onOpen={() => openPaper(paper)}
                  onDelete={() => setPendingDelete(paper)}
                />
              ))}
            </div>
          )}
        </div>
      </section>

      {/* 右列（≥1024px）：主从详情预览 */}
      <section
        aria-label="试卷详情"
        className="hidden h-full min-h-0 min-w-0 flex-1 overflow-hidden rounded-xl border border-border bg-card shadow-soft lg:block"
      >
        {selectedId ? (
          <PaperPreviewPanel paperId={selectedId} />
        ) : (
          <EmptyState
            icon={FileStack}
            title="选择一份试卷"
            description="在左侧选择试卷查看题目预览；分析与导出在完整页进行"
          />
        )}
      </section>

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除试卷</DialogTitle>
            <DialogDescription>确定要删除「{pendingDelete?.paper_name}」吗？此操作不可恢复。</DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setPendingDelete(null)} disabled={deleteMutation.isPending}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (pendingDelete) deleteMutation.mutate(pendingDelete.paper_id);
              }}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? <Spinner className="text-destructive-foreground" /> : null}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
