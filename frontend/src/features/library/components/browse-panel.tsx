import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  FileText,
  Image,
  LibraryBig,
  MoreVertical,
  PackagePlus,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  Trash2,
  Upload,
} from "lucide-react";

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
import { PAGE_SIZE, ORIGIN_LABELS, apiErrorText } from "../model/shared";
import { GaokaoImportSheet } from "./gaokao-import-sheet";

type LibraryArea = "general" | "gaokao";

const GAOKAO_SUBJECTS = [
  { value: "数学", label: "数学" },
  { value: "物理", label: "物理" },
  { value: "化学", label: "化学" },
] as const;
const currentYear = new Date().getFullYear();
const GAOKAO_YEARS = Array.from({ length: Math.max(1, currentYear - 2007 + 1) }, (_, index) => currentYear - index);

function imageCount(html?: string): number {
  return html?.match(/<(?:img|svg)\b/gi)?.length ?? 0;
}

function isVisualRangeSource(sourceNote?: string): boolean {
  return /gaokao_visual_range|visual_page_range|visual_only|site_listed_count_only/i.test(sourceNote ?? "");
}

function gaokaoSourceLabel(item: LibraryItem): string {
  const source = item.gaokao_source;
  if (!source) return "高考真题";
  return [
    source.exam_year,
    source.region,
    source.paper_variant || source.paper_name,
    source.question_number ? `第 ${source.question_number} 题` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function LibraryQuestionRow({
  item,
  selected,
  onSelect,
  actions,
}: {
  item: LibraryItem;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  actions: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const expectsDetail = Boolean(item.has_answer || item.has_analysis);
  const detailQuery = useQuery({
    queryKey: ["library-item", item.question_id],
    queryFn: () => libraryApi.getItem(item.question_id),
    enabled: expanded && expectsDetail,
    staleTime: 5 * 60_000,
  });
  const cache = (detailQuery.data?.question_cache ?? {}) as Record<string, unknown>;
  const answer = String(cache.answer ?? item.answer ?? "");
  const analysis = String(cache.analysis ?? item.analysis ?? "");
  const isGaokao = item.library_area === "gaokao" && Boolean(item.gaokao_source);

  return (
    <QuestionCard
      question={{
        question_id: item.question_id,
        stem: item.stem,
        answer,
        analysis,
        question_type: item.question_type,
        difficulty: item.difficulty,
        ai_verdict: item.ai_verdict,
        knowledge_point: item.knowledge_point,
        quality_score: item.quality_score,
        has_answer: item.has_answer,
        has_analysis: item.has_analysis,
        source: isGaokao
          ? gaokaoSourceLabel(item)
          : [item.subject, ORIGIN_LABELS[item.origin ?? ""] ?? item.origin].filter(Boolean).join(" · ") || undefined,
        source_url: isGaokao ? item.gaokao_source?.source_url : item.source_url,
      }}
      selected={selected}
      onSelect={onSelect}
      expanded={expanded}
      onExpandedChange={setExpanded}
      detailLoading={expanded && expectsDetail && detailQuery.isLoading}
      detailError={detailQuery.isError ? apiErrorText(detailQuery.error, "加载答案与解析失败") : undefined}
      onRetryDetail={() => detailQuery.refetch()}
      actions={actions}
    />
  );
}

export function BrowsePanel({ onGoGenerate }: { onGoGenerate: () => void }) {
  const queryClient = useQueryClient();
  const toast = useUiStore((state) => state.toast);
  const [searchParams, setSearchParams] = useSearchParams();
  const area = parseEnumParam(searchParams, "area", ["general", "gaokao"] as const) ?? "general";
  const isGaokao = area === "gaokao";
  const filters = useMemo(
    () => ({
      q: parseStringParam(searchParams, "q") ?? "",
      subject: parseStringParam(searchParams, "subject") ?? "all",
      questionType: parseStringParam(searchParams, "type") ?? "all",
      difficulty: parseStringParam(searchParams, "difficulty") ?? "all",
      origin: parseStringParam(searchParams, "origin") ?? "all",
      hidden: parseEnumParam(searchParams, "hidden", ["0", "1", "all"] as const) ?? "0",
      sort: parseStringParam(searchParams, "sort") ?? "updated_at:desc",
      year: parseStringParam(searchParams, "year") ?? "all",
      region: parseStringParam(searchParams, "region") ?? "",
      paperName: parseStringParam(searchParams, "paper") ?? "",
      questionNumber: parseStringParam(searchParams, "number") ?? "",
    }),
    [searchParams],
  );
  const page = parseIntParam(searchParams, "page", { min: 0 }) ?? 0;
  const [searchDraft, setSearchDraft] = useState({
    q: filters.q,
    region: filters.region,
    paperName: filters.paperName,
    questionNumber: filters.questionNumber,
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  useEffect(() => {
    setSearchDraft({
      q: filters.q,
      region: filters.region,
      paperName: filters.paperName,
      questionNumber: filters.questionNumber,
    });
  }, [filters.q, filters.region, filters.paperName, filters.questionNumber]);

  const filterUrlKeys = {
    q: "q",
    subject: "subject",
    questionType: "type",
    difficulty: "difficulty",
    origin: "origin",
    hidden: "hidden",
    sort: "sort",
    year: "year",
    region: "region",
    paperName: "paper",
    questionNumber: "number",
  } as const;
  const filterDefaults: Record<keyof typeof filters, string> = {
    q: "",
    subject: "all",
    questionType: "all",
    difficulty: "all",
    origin: "all",
    hidden: "0",
    sort: "updated_at:desc",
    year: "all",
    region: "",
    paperName: "",
    questionNumber: "",
  };

  const updateFilter = <K extends keyof typeof filters>(key: K, value: (typeof filters)[K]) => {
    setSearchParams(
      (previous) =>
        updateSearchParams(previous, {
          [filterUrlKeys[key]]: value === filterDefaults[key] ? null : value,
          page: null,
        }),
      { replace: true },
    );
  };
  const setArea = (next: string) => {
    const nextArea: LibraryArea = next === "gaokao" ? "gaokao" : "general";
    setSelected(new Set());
    setSearchParams(
      (previous) =>
        updateSearchParams(previous, {
          area: nextArea === "general" ? null : nextArea,
          page: null,
          subject: null,
          year: null,
          region: null,
          paper: null,
          number: null,
        }),
      { replace: true },
    );
  };
  const setPage = (next: number) =>
    setSearchParams((previous) => updateSearchParams(previous, { page: next > 0 ? next : null }), { replace: true });
  const applyTextFilters = () => {
    setSearchParams(
      (previous) =>
        updateSearchParams(previous, {
          q: searchDraft.q.trim() || null,
          region: isGaokao ? searchDraft.region.trim() || null : null,
          paper: isGaokao ? searchDraft.paperName.trim() || null : null,
          number: isGaokao ? searchDraft.questionNumber.trim() || null : null,
          page: null,
        }),
      { replace: true },
    );
  };

  const applied: LibraryItemsQuery = useMemo(() => {
    const [sortKey, sortOrder] = filters.sort.split(":");
    return {
      area,
      q: filters.q || undefined,
      subject: filters.subject === "all" ? undefined : filters.subject,
      question_type: filters.questionType === "all" ? undefined : filters.questionType,
      difficulty: filters.difficulty === "all" ? undefined : filters.difficulty,
      origin: filters.origin === "all" ? undefined : filters.origin,
      hidden: filters.hidden,
      year: isGaokao && filters.year !== "all" ? filters.year : undefined,
      region: isGaokao ? filters.region || undefined : undefined,
      paper_name: isGaokao ? filters.paperName || undefined : undefined,
      question_number: isGaokao ? filters.questionNumber || undefined : undefined,
      sort: sortKey === "ai_score" ? "ai_score" : "updated_at",
      order: sortOrder === "asc" ? "asc" : "desc",
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    };
  }, [area, filters, isGaokao, page]);

  const itemsQuery = useQuery({
    queryKey: ["library-items", applied],
    queryFn: () => libraryApi.items(applied),
    placeholderData: keepPreviousData,
  });
  const invalidateItems = () => queryClient.invalidateQueries({ queryKey: ["library-items"] });
  const invalidateGaokaoItems = () =>
    queryClient.invalidateQueries({
      predicate: (query) => {
        if (query.queryKey[0] !== "library-items") return false;
        const queryFilters = query.queryKey[1] as LibraryItemsQuery | undefined;
        return queryFilters?.area === "gaokao";
      },
    });

  const starMut = useMutation({
    mutationFn: ({ qid, starred }: { qid: string; starred: boolean }) =>
      starred ? libraryApi.unstar(qid) : libraryApi.star(qid),
    onSuccess: invalidateItems,
    onError: (error) => toast({ title: "星标操作失败", description: apiErrorText(error, "请稍后重试"), variant: "destructive" }),
  });
  const hideMut = useMutation({
    mutationFn: ({ qid, hidden }: { qid: string; hidden: boolean }) =>
      hidden ? libraryApi.unhide(qid) : libraryApi.hide(qid),
    onSuccess: invalidateItems,
    onError: (error) => toast({ title: "隐藏操作失败", description: apiErrorText(error, "请稍后重试"), variant: "destructive" }),
  });
  const basketMut = useMutation({
    mutationFn: (qid: string) => libraryApi.exportToBasket(qid),
    onSuccess: (result: any) => {
      if (result && result.success === false) {
        toast({ title: "加入试题篮失败", description: String(result.error || "组卷网导出失败"), variant: "warning" });
      } else {
        toast({ title: "已加入组卷网试题篮", variant: "success" });
      }
    },
    onError: (error) => toast({ title: "加入试题篮失败", description: apiErrorText(error, "请确认组卷网登录态"), variant: "destructive" }),
  });
  const bulkMut = useMutation({
    mutationFn: () => libraryApi.bulkDelete(Array.from(selected)),
    onSuccess: (result) => {
      toast({ title: "批量删除完成", description: `已删除 ${result?.deleted ?? selected.size} 题`, variant: "success" });
      setSelected(new Set());
      setBulkOpen(false);
      invalidateItems();
    },
    onError: (error) => toast({ title: "批量删除失败", description: apiErrorText(error, "请稍后重试"), variant: "destructive" }),
  });

  const toggleSelect = (qid: string, checked: boolean) => {
    setSelected((previous) => {
      const next = new Set(previous);
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

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex items-center gap-1 rounded-lg bg-muted p-1">
          <Button size="sm" variant={area === "general" ? "secondary" : "ghost"} onClick={() => setArea("general")}><LibraryBig />普通题库</Button>
          <Button size="sm" variant={area === "gaokao" ? "secondary" : "ghost"} onClick={() => setArea("gaokao")}><BadgeCheck />高考真题</Button>
        </div>
        {isGaokao ? <Button size="sm" onClick={() => setImportOpen(true)}><Upload />导入高考真题</Button> : null}
      </div>

      {isGaokao ? (
        <Alert variant="info">
          <ShieldCheck />
          <AlertDescription>真题隔离区仅展示带结构化年份、地区和试卷出处的题目，不混入模拟题或 AI 生成题。</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 p-4">
          <form
            className="contents"
            onSubmit={(event) => {
              event.preventDefault();
              applyTextFilters();
            }}
          >
            <Input
              value={searchDraft.q}
              onChange={(event) => setSearchDraft((current) => ({ ...current, q: event.target.value }))}
              placeholder={isGaokao ? "搜索题干、卷名或题号…" : "搜索题干关键词…"}
              className="min-w-52 max-w-xs flex-1"
            />

            <Select value={filters.subject} onValueChange={(value) => updateFilter("subject", value)}>
              <SelectTrigger className="w-32"><SelectValue placeholder="学科" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部学科</SelectItem>
                {(isGaokao ? GAOKAO_SUBJECTS : SUBJECTS.map((value) => ({ value, label: value }))).map((subject) => (
                  <SelectItem key={subject.value} value={subject.value}>{subject.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            {isGaokao ? (
              <>
                <Select value={filters.year} onValueChange={(value) => updateFilter("year", value)}>
                  <SelectTrigger className="w-28"><SelectValue placeholder="年份" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部年份</SelectItem>
                    {GAOKAO_YEARS.map((year) => <SelectItem key={year} value={String(year)}>{year} 年</SelectItem>)}
                  </SelectContent>
                </Select>
                <Input value={searchDraft.region} onChange={(event) => setSearchDraft((current) => ({ ...current, region: event.target.value }))} placeholder="地区" className="w-24" />
                <Input value={searchDraft.paperName} onChange={(event) => setSearchDraft((current) => ({ ...current, paperName: event.target.value }))} placeholder="卷名" className="w-32" />
                <Input value={searchDraft.questionNumber} onChange={(event) => setSearchDraft((current) => ({ ...current, questionNumber: event.target.value }))} placeholder="题号" className="w-20" />
              </>
            ) : null}

            <Select value={filters.questionType} onValueChange={(value) => updateFilter("questionType", value)}>
              <SelectTrigger className="w-28"><SelectValue placeholder="题型" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部题型</SelectItem>
                {QUESTION_TYPES.map((type) => <SelectItem key={type} value={type}>{type}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={filters.difficulty} onValueChange={(value) => updateFilter("difficulty", value)}>
              <SelectTrigger className="w-28"><SelectValue placeholder="难度" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部难度</SelectItem>
                {DIFFICULTIES.map((difficulty) => <SelectItem key={difficulty} value={difficulty}>{difficulty}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={filters.origin} onValueChange={(value) => updateFilter("origin", value)}>
              <SelectTrigger className="w-28"><SelectValue placeholder="来源" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部来源</SelectItem>
                <SelectItem value="crawled">抓取</SelectItem>
                {!isGaokao ? <SelectItem value="ai">AI 生成</SelectItem> : null}
                <SelectItem value="media">媒体录入</SelectItem>
              </SelectContent>
            </Select>
            <Select value={filters.hidden} onValueChange={(value) => updateFilter("hidden", value as "0" | "1" | "all")}>
              <SelectTrigger className="w-28"><SelectValue placeholder="可见性" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="0">未隐藏</SelectItem>
                <SelectItem value="1">已隐藏</SelectItem>
                <SelectItem value="all">全部</SelectItem>
              </SelectContent>
            </Select>
            <Select value={filters.sort} onValueChange={(value) => updateFilter("sort", value)}>
              <SelectTrigger className="w-40"><SelectValue placeholder="排序" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="updated_at:desc">最近更新</SelectItem>
                <SelectItem value="updated_at:asc">最早更新</SelectItem>
                <SelectItem value="ai_score:desc">AI 分从高到低</SelectItem>
                <SelectItem value="ai_score:asc">AI 分从低到高</SelectItem>
              </SelectContent>
            </Select>
            <Button type="submit" variant="secondary" size="sm"><Search />搜索</Button>
          </form>
        </CardContent>
      </Card>

      {itemsQuery.isLoading ? (
        <div className="space-y-3"><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /></div>
      ) : itemsQuery.isError ? (
        <Alert variant="destructive"><AlertDescription className="flex items-center justify-between gap-3"><span>{apiErrorText(itemsQuery.error, "加载题库失败")}</span><Button size="sm" variant="outline" onClick={() => itemsQuery.refetch()}>重试</Button></AlertDescription></Alert>
      ) : items.length === 0 ? (
        isGaokao ? (
          <EmptyState
            icon={BadgeCheck}
            title="暂未找到高考真题"
            description="调整年份、地区或卷名筛选，或者导入带完整结构化出处的真题。"
            action={<Button size="sm" variant="outline" onClick={() => setImportOpen(true)}><Upload />导入高考真题</Button>}
          />
        ) : (
          <EmptyState
            icon={LibraryBig}
            title="题库暂无匹配题目"
            description="调整过滤条件，或通过 AI 出题 / 题库抓取充实题库"
            action={<Button size="sm" variant="outline" onClick={onGoGenerate}><Sparkles />去 AI 出题</Button>}
          />
        )
      ) : (
        <div className="space-y-3">
          {items.map((item: LibraryItem) => {
            const source = item.gaokao_source;
            const figures = imageCount(item.stem);
            const isVisualRange = isVisualRangeSource(source?.source_note);
            return (
              <LibraryQuestionRow
                key={item.question_id}
                item={item}
                selected={selected.has(item.question_id)}
                onSelect={(checked) => toggleSelect(item.question_id, checked)}
                actions={
                  <>
                    {source ? (
                      <Badge variant={source.verified ? "success" : "warning"}>
                        {source.verified ? <BadgeCheck /> : null}
                        {source.verified ? "已核验" : "未核验"}
                      </Badge>
                    ) : null}
                    {isVisualRange ? <Badge variant="outline">视觉区间题</Badge> : null}
                    {figures > 0 ? <Badge variant="outline"><Image />图形 {figures}</Badge> : null}
                    {typeof item.ai_score === "number" ? <Badge variant="outline">AI 分 {item.ai_score}</Badge> : null}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="题目操作"><MoreVertical /></Button></DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => starMut.mutate({ qid: item.question_id, starred: Boolean(item.starred) })}><Star className={item.starred ? "fill-current text-warning" : ""} />{item.starred ? "取消星标" : "星标"}</DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => hideMut.mutate({ qid: item.question_id, hidden: Boolean(item.hidden) })}>{item.hidden ? <Eye /> : <EyeOff />}{item.hidden ? "取消隐藏" : "隐藏"}</DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onSelect={() => basketMut.mutate(item.question_id)}><PackagePlus />加入试题篮</DropdownMenuItem>
                        {source?.source_url ? <DropdownMenuItem asChild><a href={source.source_url} target="_blank" rel="noreferrer"><FileText />查看原始来源</a></DropdownMenuItem> : null}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </>
                }
              />
            );
          })}
        </div>
      )}

      {!itemsQuery.isLoading && items.length > 0 ? (
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground">第 {page + 1} 页{total != null ? ` / 共 ${total} 条` : ` / 本页 ${items.length} 条`}</span>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" disabled={!canPrev} onClick={() => setPage(Math.max(0, page - 1))}><ChevronLeft />上一页</Button>
            <Button variant="outline" size="sm" disabled={!canNext} onClick={() => setPage(page + 1)}>下一页<ChevronRight /></Button>
          </div>
        </div>
      ) : null}

      {selected.size > 0 ? (
        <div className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border border-border bg-card px-5 py-2.5 shadow-lift animate-slide-up">
          <span className="text-sm">已选 {selected.size} 题</span>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>清空</Button>
          <Button size="sm" variant="destructive" onClick={() => setBulkOpen(true)}><Trash2 />批量删除</Button>
        </div>
      ) : null}

      <Dialog open={bulkOpen} onOpenChange={setBulkOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>批量删除</DialogTitle><DialogDescription>将从题库中永久删除已选的 {selected.size} 道题，此操作不可撤销。</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="outline" onClick={() => setBulkOpen(false)}>取消</Button><Button variant="destructive" disabled={bulkMut.isPending} onClick={() => bulkMut.mutate()}>{bulkMut.isPending ? <Spinner className="text-destructive-foreground" /> : null}确认删除</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <GaokaoImportSheet open={importOpen} onOpenChange={setImportOpen} onImported={invalidateGaokaoItems} />
    </div>
  );
}
