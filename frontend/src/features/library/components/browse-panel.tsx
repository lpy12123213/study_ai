import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Eye, EyeOff, FileText, LibraryBig, MoreVertical, PackagePlus, Search, Sparkles, Star, Trash2 } from "lucide-react";
import { libraryApi } from "@/features/question-library/api";
import type { LibraryItemsQuery } from "@/features/question-library/api";
import { DIFFICULTIES, QUESTION_TYPES, SUBJECTS } from "@/shared/api/types";
import type { LibraryItem } from "@/shared/api/types";
import { parseEnumParam, parseIntParam, parseStringParam, updateSearchParams } from "@/shared/lib/search-params";
import { useUiStore } from "@/stores/ui";
import { QuestionCard } from "@/components/question/question-card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { PAGE_SIZE } from "../model/shared";
import { ORIGIN_LABELS } from "../model/shared";
import { apiErrorText } from "../model/shared";
import { ItemDetailSheet } from "./item-detail-sheet";


// ---------------- 题库浏览 ----------------

export function BrowsePanel({ onGoGenerate }: { onGoGenerate: () => void }) {
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);
  // 筛选/分页/详情入 URL（架构 §8.4）：可分享，刷新与后退可恢复
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(
    () => ({
      q: parseStringParam(searchParams, "q") ?? "",
      subject: parseStringParam(searchParams, "subject") ?? "all",
      questionType: parseStringParam(searchParams, "type") ?? "all",
      difficulty: parseStringParam(searchParams, "difficulty") ?? "all",
      origin: parseStringParam(searchParams, "origin") ?? "all",
      hidden: parseEnumParam(searchParams, "hidden", ["0", "1", "all"] as const) ?? "0",
      sort: parseStringParam(searchParams, "sort") ?? "updated_at:desc",
    }),
    [searchParams],
  );
  const page = parseIntParam(searchParams, "page", { min: 0 }) ?? 0;
  const detailId = parseStringParam(searchParams, "detail") ?? null;
  const [qInput, setQInput] = useState(filters.q);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);

  const filterUrlKeys = {
    q: "q",
    subject: "subject",
    questionType: "type",
    difficulty: "difficulty",
    origin: "origin",
    hidden: "hidden",
    sort: "sort",
  } as const;
  const filterDefaults: Record<keyof typeof filters, string> = {
    q: "",
    subject: "all",
    questionType: "all",
    difficulty: "all",
    origin: "all",
    hidden: "0",
    sort: "updated_at:desc",
  };

  const updateFilter = <K extends keyof typeof filters>(key: K, value: (typeof filters)[K]) => {
    // 默认值不占 URL；任何筛选变化都回到第 0 页
    setSearchParams(
      (prev) =>
        updateSearchParams(prev, { [filterUrlKeys[key]]: value === filterDefaults[key] ? null : value, page: null }),
      { replace: true },
    );
  };
  const setPage = (next: number) =>
    setSearchParams((prev) => updateSearchParams(prev, { page: next > 0 ? next : null }), { replace: true });
  // 打开详情产生历史条目（返回键关闭）；关闭用 replace 不新增条目
  const openDetail = (qid: string) => setSearchParams((prev) => updateSearchParams(prev, { detail: qid }));
  const closeDetail = () => setSearchParams((prev) => updateSearchParams(prev, { detail: null }), { replace: true });

  const applied: LibraryItemsQuery = useMemo(() => {
    const [sortKey, sortOrder] = filters.sort.split(":");
    return {
      q: filters.q || undefined,
      subject: filters.subject === "all" ? undefined : filters.subject,
      question_type: filters.questionType === "all" ? undefined : filters.questionType,
      difficulty: filters.difficulty === "all" ? undefined : filters.difficulty,
      origin: filters.origin === "all" ? undefined : filters.origin,
      hidden: filters.hidden,
      sort: sortKey === "ai_score" ? "ai_score" : "updated_at",
      order: sortOrder === "asc" ? "asc" : "desc",
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    };
  }, [filters, page]);

  const itemsQuery = useQuery({
    queryKey: ["library-items", applied],
    queryFn: () => libraryApi.items(applied),
    placeholderData: keepPreviousData,
  });

  const invalidateItems = () => queryClient.invalidateQueries({ queryKey: ["library-items"] });

  const starMut = useMutation({
    mutationFn: ({ qid, starred }: { qid: string; starred: boolean }) =>
      starred ? libraryApi.unstar(qid) : libraryApi.star(qid),
    onSuccess: invalidateItems,
    onError: (err) => toast({ title: "星标操作失败", description: apiErrorText(err, "请稍后重试"), variant: "destructive" }),
  });

  const hideMut = useMutation({
    mutationFn: ({ qid, hidden }: { qid: string; hidden: boolean }) =>
      hidden ? libraryApi.unhide(qid) : libraryApi.hide(qid),
    onSuccess: invalidateItems,
    onError: (err) => toast({ title: "隐藏操作失败", description: apiErrorText(err, "请稍后重试"), variant: "destructive" }),
  });

  const basketMut = useMutation({
    mutationFn: (qid: string) => libraryApi.exportToBasket(qid),
    onSuccess: (res: any) => {
      if (res && res.success === false) {
        toast({ title: "加入试题篮失败", description: String(res.error || "组卷网导出失败"), variant: "warning" });
      } else {
        toast({ title: "已加入组卷网试题篮", variant: "success" });
      }
    },
    onError: (err) =>
      toast({ title: "加入试题篮失败", description: apiErrorText(err, "请确认组卷网登录态"), variant: "destructive" }),
  });

  const bulkMut = useMutation({
    mutationFn: () => libraryApi.bulkDelete(Array.from(selected)),
    onSuccess: (res) => {
      toast({ title: "批量删除完成", description: `已删除 ${res?.deleted ?? selected.size} 题`, variant: "success" });
      setSelected(new Set());
      setBulkOpen(false);
      invalidateItems();
    },
    onError: (err) => toast({ title: "批量删除失败", description: apiErrorText(err, "请稍后重试"), variant: "destructive" }),
  });

  const toggleSelect = (qid: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(qid);
      else next.delete(qid);
      return next;
    });
  };

  const data = itemsQuery.data;
  const items = data?.items ?? [];
  const total = data?.total ?? null;
  const canPrev = page > 0;
  const canNext = total != null ? (page + 1) * PAGE_SIZE < total : items.length === PAGE_SIZE;

  const applySearch = () => {
    updateFilter("q", qInput.trim());
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 p-4">
          <form
            className="flex min-w-52 flex-1 items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              applySearch();
            }}
          >
            <Input
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              placeholder="搜索题干关键词…"
              className="max-w-xs"
            />
            <Button type="submit" variant="secondary" size="sm">
              <Search />
              搜索
            </Button>
          </form>

          <Select value={filters.subject} onValueChange={(v) => updateFilter("subject", v)}>
            <SelectTrigger className="w-32">
              <SelectValue placeholder="学科" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部学科</SelectItem>
              {SUBJECTS.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={filters.questionType} onValueChange={(v) => updateFilter("questionType", v)}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="题型" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部题型</SelectItem>
              {QUESTION_TYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={filters.difficulty} onValueChange={(v) => updateFilter("difficulty", v)}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="难度" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部难度</SelectItem>
              {DIFFICULTIES.map((d) => (
                <SelectItem key={d} value={d}>
                  {d}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={filters.origin} onValueChange={(v) => updateFilter("origin", v)}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="来源" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部来源</SelectItem>
              <SelectItem value="crawled">抓取</SelectItem>
              <SelectItem value="ai">AI 生成</SelectItem>
              <SelectItem value="media">媒体录入</SelectItem>
            </SelectContent>
          </Select>

          <Select value={filters.hidden} onValueChange={(v) => updateFilter("hidden", v as "0" | "1" | "all")}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="可见性" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">未隐藏</SelectItem>
              <SelectItem value="1">已隐藏</SelectItem>
              <SelectItem value="all">全部</SelectItem>
            </SelectContent>
          </Select>

          <Select value={filters.sort} onValueChange={(v) => updateFilter("sort", v)}>
            <SelectTrigger className="w-40">
              <SelectValue placeholder="排序" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="updated_at:desc">最近更新</SelectItem>
              <SelectItem value="updated_at:asc">最早更新</SelectItem>
              <SelectItem value="ai_score:desc">AI 分从高到低</SelectItem>
              <SelectItem value="ai_score:asc">AI 分从低到高</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {itemsQuery.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : itemsQuery.isError ? (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-3">
            <span>{apiErrorText(itemsQuery.error, "加载题库失败")}</span>
            <Button size="sm" variant="outline" onClick={() => itemsQuery.refetch()}>
              重试
            </Button>
          </AlertDescription>
        </Alert>
      ) : items.length === 0 ? (
        <EmptyState
          icon={LibraryBig}
          title="题库暂无匹配题目"
          description="调整过滤条件，或通过 AI 出题 / 题库抓取充实题库"
          action={
            <Button size="sm" variant="outline" onClick={onGoGenerate}>
              <Sparkles />
              去 AI 出题
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {items.map((item: LibraryItem) => (
            <QuestionCard
              key={item.question_id}
              question={{
                question_id: item.question_id,
                stem: item.stem,
                question_type: item.question_type,
                difficulty: item.difficulty,
                ai_verdict: item.ai_verdict,
                source:
                  [item.subject, ORIGIN_LABELS[item.origin ?? ""] ?? item.origin].filter(Boolean).join(" · ") ||
                  undefined,
              }}
              selected={selected.has(item.question_id)}
              onSelect={(checked) => toggleSelect(item.question_id, checked)}
              actions={
                <>
                  {typeof item.ai_score === "number" ? <Badge variant="outline">AI 分 {item.ai_score}</Badge> : null}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon-sm" aria-label="题目操作">
                        <MoreVertical />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => openDetail(item.question_id)}>
                        <FileText />
                        查看详情
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() => starMut.mutate({ qid: item.question_id, starred: !!item.starred })}
                      >
                        <Star className={item.starred ? "fill-current text-warning" : ""} />
                        {item.starred ? "取消星标" : "星标"}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onSelect={() => hideMut.mutate({ qid: item.question_id, hidden: !!item.hidden })}
                      >
                        {item.hidden ? <Eye /> : <EyeOff />}
                        {item.hidden ? "取消隐藏" : "隐藏"}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onSelect={() => basketMut.mutate(item.question_id)}>
                        <PackagePlus />
                        加入试题篮
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </>
              }
            />
          ))}
        </div>
      )}

      {!itemsQuery.isLoading && items.length > 0 ? (
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground">
            第 {page + 1} 页{total != null ? ` / 共 ${total} 条` : ` / 本页 ${items.length} 条`}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" disabled={!canPrev} onClick={() => setPage(Math.max(0, page - 1))}>
              <ChevronLeft />
              上一页
            </Button>
            <Button variant="outline" size="sm" disabled={!canNext} onClick={() => setPage(page + 1)}>
              下一页
              <ChevronRight />
            </Button>
          </div>
        </div>
      ) : null}

      {selected.size > 0 ? (
        <div className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border border-border bg-card px-5 py-2.5 shadow-lift animate-slide-up">
          <span className="text-sm">已选 {selected.size} 题</span>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            清空
          </Button>
          <Button size="sm" variant="destructive" onClick={() => setBulkOpen(true)}>
            <Trash2 />
            批量删除
          </Button>
        </div>
      ) : null}

      <Dialog open={bulkOpen} onOpenChange={setBulkOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>批量删除</DialogTitle>
            <DialogDescription>
              将从题库中永久删除已选的 {selected.size} 道题，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBulkOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" disabled={bulkMut.isPending} onClick={() => bulkMut.mutate()}>
              {bulkMut.isPending ? <Spinner className="text-destructive-foreground" /> : null}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {detailId ? <ItemDetailSheet questionId={detailId} onClose={closeDetail} /> : null}
    </div>
  );
}

