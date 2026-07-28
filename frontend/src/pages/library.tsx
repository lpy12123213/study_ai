import { useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Brain,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  CloudDownload,
  Eye,
  EyeOff,
  FileText,
  History,
  LibraryBig,
  MoreVertical,
  PackagePlus,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  StopCircle,
  Trash2,
} from "lucide-react";

import { ApiError } from "@/shared/api/http-client";
import { tasksApi } from "@/features/task-center/api";
import {
  crawlLibrary,
  generateLibraryQuestions,
  libraryApi,
  scoreLibrary,
  type LibraryItemsQuery,
} from "@/features/question-library/api";
import {
  DEFAULT_SUBJECT,
  DIFFICULTIES,
  EDU_LEVELS,
  QUESTION_TYPES,
  SUBJECTS,
  type DraftQuestion,
  type LibraryItem,
  type LibraryPreview,
  type TaskEvent,
  type TaskStep,
} from "@/shared/api/types";
import type { StreamHandlers } from "@/lib/sse";
import { parseEnumParam, parseIntParam, parseStringParam, updateSearchParams } from "@/shared/lib/search-params";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";
import { cn } from "@/lib/utils";
import { clamp } from "@/lib/format";
import { generatedFileUrl, proxyImageUrl } from "@/lib/media";
import { QuestionCard } from "@/components/question/question-card";
import { StemHtml } from "@/components/question/stem-html";
import { SubjectSelect } from "@/components/question/subject-select";
import { TaskProgressPanel } from "@/components/task/task-progress-panel";
import { StepTimeline } from "@/components/task/step-timeline";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

// ---------------- 常量 ----------------

const PAGE_SIZE = 20;

const ORIGIN_LABELS: Record<string, string> = {
  crawled: "抓取",
  ai: "AI 生成",
  media: "媒体录入",
};

/** AI 出题 11 阶段（与 backend/generation/question_library/stages.py 对齐） */
const GENERATION_STAGES = [
  { id: "source_pack", label: "素材整理", order: 1 },
  { id: "curriculum_context", label: "课标对齐", order: 2 },
  { id: "reference_crawl", label: "参考题爬取", order: 3 },
  { id: "reference_analysis", label: "参考题分析", order: 4 },
  { id: "brainstorm", label: "直觉原子设计", order: 5 },
  { id: "spec_search", label: "练习包设计", order: 6 },
  { id: "draft_realization", label: "练习包生成", order: 7 },
  { id: "diagram_generation", label: "配图生成", order: 8 },
  { id: "judge", label: "快速校验", order: 9 },
  { id: "final_selection", label: "练习包去重", order: 10 },
  { id: "pending_review", label: "待审核预览", order: 11 },
] as const;

type SectionKey = "stem" | "answer" | "analysis";

// ---------------- 工具函数 ----------------

function apiErrorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}

function parseKnowledgePoints(raw: string): string[] {
  return raw
    .split(/[,，、;；\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 20);
}

function verdictVariant(verdict?: string): "success" | "warning" | "destructive" | "muted" {
  if (!verdict) return "muted";
  if (verdict.includes("好")) return "success";
  if (verdict.includes("差")) return "destructive";
  if (verdict.includes("普通")) return "warning";
  return "muted";
}

// ---------------- 流式任务 hook（POST 即流 → tasks store） ----------------

function useTaskStream(type: string) {
  const toast = useUiStore((s) => s.toast);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const start = (
    title: string,
    run: (handlers: StreamHandlers) => void,
    opts?: {
      onEvent?: (ev: TaskEvent) => void;
      onDoneEvent?: (data: any) => void;
      onError?: (err: Error) => void;
    },
  ) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setTaskId(null);
    let localId = "";
    run({
      signal: controller.signal,
      onEvent: (ev) => {
        if (ev.taskId && !localId) {
          localId = ev.taskId;
          setTaskId(ev.taskId);
          useTasksStore.getState().register(ev.taskId, { type, title });
        }
        if (localId) useTasksStore.getState().applyEvent(localId, ev);
        opts?.onEvent?.(ev);
        if (ev.type === "done" || ev.type === "result") {
          opts?.onDoneEvent?.(ev.data ?? {});
        }
      },
      onDone: () => setRunning(false),
      onError: (err) => {
        setRunning(false);
        if (opts?.onError) opts.onError(err);
        else toast({ title: "任务失败", description: err.message || "流式任务异常中断", variant: "destructive" });
      },
    });
  };

  const stop = () => {
    abortRef.current?.abort();
    // abort 只断开前端流，服务端任务仍在运行——尽力经任务中心取消（题库任务注册在共享任务运行时）
    if (taskId) {
      tasksApi.cancel(taskId).catch(() => undefined);
    }
  };

  return { taskId, running, start, stop };
}

// ---------------- 题目详情（右侧 Sheet，Master-Detail §5.3） ----------------

function ItemDetailSheet({ questionId, onClose }: { questionId: string; onClose: () => void }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["library-item", questionId],
    queryFn: () => libraryApi.getItem(questionId),
  });

  const item = (data?.library_item ?? {}) as Record<string, unknown>;
  const cache = (data?.question_cache ?? {}) as Record<string, unknown>;
  const stem = String(cache.stem || item.stem || "");
  const answer = String(cache.answer || "");
  const analysis = String(cache.analysis || "");
  const entries = Object.entries(item).filter(
    ([k, v]) => k !== "stem" && v !== null && v !== undefined && v !== "",
  );

  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="flex w-full max-w-xl flex-col gap-0 p-0 sm:max-w-xl">
        <SheetHeader className="shrink-0 border-b border-border px-5 py-4">
          <SheetTitle>题目详情</SheetTitle>
          <SheetDescription className="font-mono text-xs">{questionId}</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : isError ? (
            <Alert variant="destructive">
              <AlertDescription>{apiErrorText(error, "加载题目详情失败")}</AlertDescription>
            </Alert>
          ) : (
            <>
              {stem ? (
                <div>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">题干</div>
                  <StemHtml html={stem} className="text-sm" />
                </div>
              ) : null}
              {answer ? (
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="mb-1 text-xs font-medium text-muted-foreground">答案</div>
                  <StemHtml html={answer} className="text-sm" />
                </div>
              ) : null}
              {analysis ? (
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="mb-1 text-xs font-medium text-muted-foreground">解析</div>
                  <StemHtml html={analysis} className="text-sm" />
                </div>
              ) : null}
              {entries.length > 0 ? (
                <div className="rounded-lg border border-border p-3">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">题库条目字段</div>
                  <div>
                    {entries.map(([k, v]) => (
                      <div
                        key={k}
                        className="grid grid-cols-[8.5rem_1fr] gap-2 border-b border-border/60 py-1.5 text-xs last:border-0"
                      >
                        <span className="font-mono text-muted-foreground">{k}</span>
                        <span className="break-all">
                          {typeof v === "object" ? JSON.stringify(v) : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ---------------- 题库浏览 ----------------

function BrowsePanel({ onGoGenerate }: { onGoGenerate: () => void }) {
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

// ---------------- AI 出题 ----------------

function GeneratePanel({ onPreview }: { onPreview: (p: LibraryPreview) => void }) {
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);
  const stream = useTaskStream("question_library_generate");
  const [form, setForm] = useState({
    subject: DEFAULT_SUBJECT as string,
    topic: "",
    difficulty: "all",
    questionType: "all",
    count: 5,
    mode: "standard" as "standard" | "infinite",
    knowledgePoints: "",
    useStudyArchive: true,
    useReferenceQuestions: true,
    referenceSource: "any" as "any" | "gaokao" | "mock" | "joint",
    referenceYearRange: "all" as "all" | "3" | "5",
    streamReasoning: false,
  });
  const [stageMap, setStageMap] = useState<Record<string, { label: string; order: number; summary: string }>>({});
  const [finished, setFinished] = useState(false);
  const [reasoning, setReasoning] = useState("");
  const [reasoningOpen, setReasoningOpen] = useState(true);

  const setField = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const currentOrder = useMemo(
    () => Math.max(0, ...Object.values(stageMap).map((s) => s.order)),
    [stageMap],
  );

  const steps: TaskStep[] = useMemo(
    () =>
      GENERATION_STAGES.map((s) => {
        const seen = stageMap[s.id];
        let status = "pending";
        if (finished) status = "completed";
        else if (seen) status = s.order < currentOrder ? "completed" : "running";
        return {
          id: s.id,
          title: seen?.summary ? `${s.label}（${seen.summary}）` : s.label,
          status,
        };
      }),
    [stageMap, finished, currentOrder],
  );

  const hasProgress = Object.keys(stageMap).length > 0 || stream.running || stream.taskId !== null;

  const submit = () => {
    const topic = form.topic.trim();
    if (!form.subject) {
      toast({ title: "请选择学科", variant: "warning" });
      return;
    }
    if (!topic) {
      toast({ title: "请填写主题", description: "例如：二次函数", variant: "warning" });
      return;
    }
    setStageMap({});
    setFinished(false);
    setReasoning("");
    stream.start(
      `${topic} 出题`,
      (handlers) =>
        generateLibraryQuestions(
          {
            subject: form.subject,
            topic,
            difficulty: form.difficulty === "all" ? "" : form.difficulty,
            question_type: form.questionType === "all" ? "" : form.questionType,
            count: clamp(Math.round(form.count) || 5, 1, 30),
            mode: form.mode,
            knowledge_points: parseKnowledgePoints(form.knowledgePoints),
            use_study_archive: form.useStudyArchive,
            use_reference_questions: form.useReferenceQuestions,
            reference_source: form.referenceSource,
            reference_year_range: form.referenceYearRange,
            stream_reasoning: form.streamReasoning,
          },
          handlers,
        ),
      {
        onEvent: (ev) => {
          if (ev.type === "progress") {
            const sid = String(ev.data?.stage_id || ev.data?.phase || "");
            if (sid) {
              setStageMap((m) => ({
                ...m,
                [sid]: {
                  label: String(ev.data?.stage_label || ev.data?.label || sid),
                  order: Number(ev.data?.stage_order) || 999,
                  summary: String(ev.data?.summary || ""),
                },
              }));
            }
          } else if (ev.type === "reasoning_delta") {
            const c = typeof ev.data?.content === "string" ? ev.data.content : "";
            if (c) setReasoning((t) => (t + c).slice(-60000));
          } else if (ev.type === "reasoning_status") {
            const msg = typeof ev.data?.message === "string" ? ev.data.message : "";
            if (msg) {
              const label = String(ev.data?.stage_label || "推理");
              setReasoning((t) => `${t}${t ? "\n" : ""}【${label}】${msg}`.slice(-60000));
            }
          }
        },
        onDoneEvent: (data) => {
          setFinished(true);
          queryClient.invalidateQueries({ queryKey: ["library-latest-pending-preview"] });
          const pid = String(data?.preview_id || data?.result?.preview_id || "");
          if (!pid) return;
          libraryApi
            .preview(pid)
            .then((pv) => {
              toast({
                title: "出题完成",
                description: `已生成 ${pv.draft_count ?? pv.draft_questions?.length ?? 0} 道草稿，请审核`,
                variant: "success",
              });
              onPreview(pv);
            })
            .catch((err) =>
              toast({ title: "加载预览失败", description: apiErrorText(err, "请稍后重试"), variant: "destructive" }),
            );
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="size-4 text-primary" />
            AI 出题
          </CardTitle>
          <CardDescription>基于学习资料与参考题生成新题，完成后进入预览审核再入库</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>学科（必填）</Label>
              <SubjectSelect value={form.subject} onValueChange={(v) => setField("subject", v)} />
            </div>
            <div className="space-y-1.5">
              <Label>主题（必填）</Label>
              <Input
                value={form.topic}
                onChange={(e) => setField("topic", e.target.value)}
                placeholder="例如：二次函数"
              />
            </div>
            <div className="space-y-1.5">
              <Label>难度</Label>
              <Select value={form.difficulty} onValueChange={(v) => setField("difficulty", v)}>
                <SelectTrigger>
                  <SelectValue placeholder="不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">不限</SelectItem>
                  {DIFFICULTIES.map((d) => (
                    <SelectItem key={d} value={d}>
                      {d}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>题型</Label>
              <Select value={form.questionType} onValueChange={(v) => setField("questionType", v)}>
                <SelectTrigger>
                  <SelectValue placeholder="不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">不限</SelectItem>
                  {QUESTION_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>数量（1-30）</Label>
              <Input
                type="number"
                min={1}
                max={30}
                value={form.count}
                onChange={(e) => setField("count", Number(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>生成模式</Label>
              <RadioGroup
                value={form.mode}
                onValueChange={(v) => setField("mode", v as "standard" | "infinite")}
                className="flex h-9 items-center gap-4"
              >
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <RadioGroupItem value="standard" />
                  标准批次
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <RadioGroupItem value="infinite" />
                  持续生成
                </label>
              </RadioGroup>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>知识点（逗号分隔，可空）</Label>
            <Input
              value={form.knowledgePoints}
              onChange={(e) => setField("knowledgePoints", e.target.value)}
              placeholder="例如：顶点式，判别式，韦达定理"
            />
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
              <span className="text-sm">使用学习资料</span>
              <Switch checked={form.useStudyArchive} onCheckedChange={(v) => setField("useStudyArchive", v)} />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
              <span className="text-sm">使用参考题</span>
              <Switch
                checked={form.useReferenceQuestions}
                onCheckedChange={(v) => setField("useReferenceQuestions", v)}
              />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
              <span className="text-sm">透传生成推理</span>
              <Switch checked={form.streamReasoning} onCheckedChange={(v) => setField("streamReasoning", v)} />
            </label>
          </div>

          {form.useReferenceQuestions ? (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label>参考题来源</Label>
                <Select
                  value={form.referenceSource}
                  onValueChange={(v) => setField("referenceSource", v as typeof form.referenceSource)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="any">不限来源</SelectItem>
                    <SelectItem value="gaokao">高考</SelectItem>
                    <SelectItem value="mock">模拟</SelectItem>
                    <SelectItem value="joint">联考</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>参考题年份范围</Label>
                <Select
                  value={form.referenceYearRange}
                  onValueChange={(v) => setField("referenceYearRange", v as typeof form.referenceYearRange)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部年份</SelectItem>
                    <SelectItem value="3">近 3 年</SelectItem>
                    <SelectItem value="5">近 5 年</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : null}

          <div className="flex items-center gap-2">
            <Button onClick={submit} disabled={stream.running}>
              {stream.running ? <Spinner className="text-primary-foreground" /> : <Sparkles />}
              {stream.running ? "生成中…" : "开始出题"}
            </Button>
            {stream.running ? (
              <Button variant="outline" onClick={stream.stop}>
                <StopCircle />
                停止
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {hasProgress ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">生成进度</CardTitle>
            <CardDescription>出题流水线共 11 个阶段，完成后自动进入预览审核</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {stream.taskId ? <TaskProgressPanel taskId={stream.taskId} showSteps={false} /> : null}
            <StepTimeline steps={steps} />
          </CardContent>
        </Card>
      ) : null}

      {form.streamReasoning && (reasoning || stream.running) ? (
        <Card>
          <CardHeader className="pb-2">
            <button
              type="button"
              className="flex w-full cursor-pointer items-center justify-between text-left"
              onClick={() => setReasoningOpen((v) => !v)}
            >
              <CardTitle className="flex items-center gap-2 text-base">
                <Brain className="size-4 text-primary" />
                生成推理
              </CardTitle>
              <span className="text-xs text-muted-foreground">{reasoningOpen ? "收起" : "展开"}</span>
            </button>
          </CardHeader>
          {reasoningOpen ? (
            <CardContent>
              {reasoning ? (
                <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted/60 p-3 font-mono text-xs leading-relaxed text-muted-foreground">
                  {reasoning}
                </pre>
              ) : (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Spinner />
                  等待模型推理输出…
                </div>
              )}
            </CardContent>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

// ---------------- 抓取与评分 ----------------

function CrawlScorePanel() {
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);
  const crawlStream = useTaskStream("question_library_crawl");
  const scoreStream = useTaskStream("question_library_score");
  const [crawlOpen, setCrawlOpen] = useState(false);
  const [scoreOpen, setScoreOpen] = useState(false);
  const [crawlForm, setCrawlForm] = useState({
    query: "",
    subject: "all",
    eduLevel: "all",
    difficulty: "all",
    questionType: "all",
    limit: 30,
    maxPages: 2,
    minQuality: 0,
  });
  const [scoreForm, setScoreForm] = useState({
    subject: DEFAULT_SUBJECT as string,
    limit: 50,
    onlyUnscored: true,
  });

  const setCrawl = <K extends keyof typeof crawlForm>(key: K, value: (typeof crawlForm)[K]) =>
    setCrawlForm((f) => ({ ...f, [key]: value }));
  const setScore = <K extends keyof typeof scoreForm>(key: K, value: (typeof scoreForm)[K]) =>
    setScoreForm((f) => ({ ...f, [key]: value }));

  const submitCrawl = () => {
    const query = crawlForm.query.trim();
    if (!query) {
      toast({ title: "请填写抓取关键词", variant: "warning" });
      return;
    }
    crawlStream.start(
      `抓取：${query}`,
      (handlers) =>
        crawlLibrary(
          {
            query,
            subject: crawlForm.subject === "all" ? "" : crawlForm.subject,
            edu_level: crawlForm.eduLevel === "all" ? "" : crawlForm.eduLevel,
            difficulty: crawlForm.difficulty === "all" ? "" : crawlForm.difficulty,
            question_type: crawlForm.questionType === "all" ? "" : crawlForm.questionType,
            limit: clamp(Math.round(crawlForm.limit) || 30, 1, 200),
            max_pages: clamp(Math.round(crawlForm.maxPages) || 2, 1, 50),
            min_quality_score: clamp(Math.round(crawlForm.minQuality) || 0, 0, 100),
          },
          handlers,
        ),
      {
        onDoneEvent: (data) => {
          toast({
            title: "抓取完成",
            description: `已入库 ${Number(data?.inserted ?? data?.count ?? 0)} 题`,
            variant: "success",
          });
          queryClient.invalidateQueries({ queryKey: ["library-items"] });
        },
      },
    );
  };

  const submitScore = () => {
    if (!scoreForm.subject) {
      toast({ title: "请选择学科", variant: "warning" });
      return;
    }
    scoreStream.start(
      `${scoreForm.subject} 评分`,
      (handlers) =>
        scoreLibrary(
          {
            subject: scoreForm.subject,
            limit: clamp(Math.round(scoreForm.limit) || 50, 1, 500),
            only_unscored: scoreForm.onlyUnscored,
          },
          handlers,
        ),
      {
        onDoneEvent: (data) => {
          const scored = Number(data?.scored ?? data?.count ?? 0);
          const hidden = Number(data?.hidden ?? 0);
          toast({
            title: "评分完成",
            description: `已评分 ${scored} 题${hidden > 0 ? `，自动隐藏低分 ${hidden} 题` : ""}`,
            variant: "success",
          });
          queryClient.invalidateQueries({ queryKey: ["library-items"] });
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <CloudDownload className="size-4 text-primary" />
              题库抓取
            </CardTitle>
            <CardDescription>从组卷网按关键词抓取题目并写入本地题库</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setCrawlOpen(true)}>
              <CloudDownload />
              开始抓取
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ClipboardCheck className="size-4 text-primary" />
              AI 评分清洗
            </CardTitle>
            <CardDescription>为题库题目批量 AI 评分，低分题自动隐藏</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setScoreOpen(true)}>
              <ClipboardCheck />
              开始评分
            </Button>
          </CardContent>
        </Card>
      </div>

      <Dialog open={crawlOpen} onOpenChange={setCrawlOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>题库抓取</DialogTitle>
            <DialogDescription>按关键词从组卷网检索题目并解析入库，过程可实时观察</DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
            <div className="space-y-1.5">
              <Label>关键词（必填）</Label>
              <Input
                value={crawlForm.query}
                onChange={(e) => setCrawl("query", e.target.value)}
                placeholder="例如：二次函数最值"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label>学科</Label>
                <Select value={crawlForm.subject} onValueChange={(v) => setCrawl("subject", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="不限" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">不限</SelectItem>
                    {SUBJECTS.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>学段</Label>
                <Select value={crawlForm.eduLevel} onValueChange={(v) => setCrawl("eduLevel", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="不限" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">不限</SelectItem>
                    {EDU_LEVELS.map((l) => (
                      <SelectItem key={l} value={l}>
                        {l}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>难度</Label>
                <Select value={crawlForm.difficulty} onValueChange={(v) => setCrawl("difficulty", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="不限" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">不限</SelectItem>
                    {DIFFICULTIES.map((d) => (
                      <SelectItem key={d} value={d}>
                        {d}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>题型</Label>
                <Select value={crawlForm.questionType} onValueChange={(v) => setCrawl("questionType", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="不限" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">不限</SelectItem>
                    {QUESTION_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>抓取数量（1-200）</Label>
                <Input
                  type="number"
                  min={1}
                  max={200}
                  value={crawlForm.limit}
                  onChange={(e) => setCrawl("limit", Number(e.target.value))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>最大页数（1-50）</Label>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={crawlForm.maxPages}
                  onChange={(e) => setCrawl("maxPages", Number(e.target.value))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>最低质量分（0-100）</Label>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={crawlForm.minQuality}
                  onChange={(e) => setCrawl("minQuality", Number(e.target.value))}
                />
              </div>
            </div>
            {crawlStream.taskId ? <TaskProgressPanel taskId={crawlStream.taskId} /> : null}
          </div>
          <DialogFooter>
            {crawlStream.running ? (
              <Button variant="outline" onClick={crawlStream.stop}>
                <StopCircle />
                停止
              </Button>
            ) : null}
            <Button onClick={submitCrawl} disabled={crawlStream.running}>
              {crawlStream.running ? <Spinner className="text-primary-foreground" /> : <CloudDownload />}
              {crawlStream.running ? "抓取中…" : "开始抓取"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={scoreOpen} onOpenChange={setScoreOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>AI 评分清洗</DialogTitle>
            <DialogDescription>按学科批量评分题库题目，低分题将被自动隐藏</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label>学科（必填）</Label>
              <SubjectSelect value={scoreForm.subject} onValueChange={(v) => setScore("subject", v)} />
            </div>
            <div className="space-y-1.5">
              <Label>评分数量上限</Label>
              <Input
                type="number"
                min={1}
                max={500}
                value={scoreForm.limit}
                onChange={(e) => setScore("limit", Number(e.target.value))}
              />
            </div>
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
              <span className="text-sm">仅评未评分题目</span>
              <Switch checked={scoreForm.onlyUnscored} onCheckedChange={(v) => setScore("onlyUnscored", v)} />
            </label>
            {scoreStream.taskId ? <TaskProgressPanel taskId={scoreStream.taskId} /> : null}
          </div>
          <DialogFooter>
            {scoreStream.running ? (
              <Button variant="outline" onClick={scoreStream.stop}>
                <StopCircle />
                停止
              </Button>
            ) : null}
            <Button onClick={submitScore} disabled={scoreStream.running}>
              {scoreStream.running ? <Spinner className="text-primary-foreground" /> : <ClipboardCheck />}
              {scoreStream.running ? "评分中…" : "开始评分"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------- 预览审核 ----------------

function RegenButton({
  active,
  disabled,
  onClick,
}: {
  active: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="h-6 px-2 text-xs text-muted-foreground"
      disabled={disabled}
      onClick={onClick}
    >
      {active ? <Spinner /> : <RefreshCw />}
      重新生成
    </Button>
  );
}

function DraftCard({
  index,
  draft,
  regenKey,
  onToggleKeep,
  onRegenerate,
}: {
  index: number;
  draft: DraftQuestion;
  regenKey: string | null;
  onToggleKeep: (checked: boolean) => void;
  onRegenerate: (section: SectionKey) => void;
}) {
  const review = draft.review ?? null;
  const keyFor = (section: SectionKey) => `${draft.question_id}:${section}`;

  const sectionHeader = (label: string, section: SectionKey) => (
    <div className="mb-1 flex items-center justify-between gap-2">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <RegenButton
        active={regenKey === keyFor(section)}
        disabled={regenKey !== null}
        onClick={() => onRegenerate(section)}
      />
    </div>
  );

  const sectionBody = (section: SectionKey, html?: string) => {
    // 后端 regenerate-section 只发 progress/done（无增量事件），进行中展示加载态
    if (regenKey === keyFor(section)) {
      return (
        <div className="flex items-center gap-2 rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">
          <Spinner />
          正在重新生成…
        </div>
      );
    }
    return html ? (
      <StemHtml html={html} className="text-sm" />
    ) : (
      <span className="text-xs text-muted-foreground">（空）</span>
    );
  };

  return (
    <Card className={cn("p-4 transition-shadow", draft.keep === false && "opacity-60")}>
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">第 {index + 1} 题</Badge>
            {review?.verdict ? <Badge variant={verdictVariant(review.verdict)}>{review.verdict}</Badge> : null}
            {typeof review?.overall_score === "number" ? (
              <Badge variant="outline">综合 {review.overall_score} 分</Badge>
            ) : null}
            <span className="font-mono text-[10px] text-muted-foreground">{draft.question_id}</span>
          </div>
          <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm">
            <Checkbox checked={draft.keep !== false} onCheckedChange={(v) => onToggleKeep(v === true)} />
            保留
          </label>
        </div>

        <div>
          {sectionHeader("题干", "stem")}
          {sectionBody("stem", draft.stem)}
        </div>

        {Array.isArray(draft.diagrams) && draft.diagrams.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {draft.diagrams.map((d, i) => {
              const src = d?.url ? proxyImageUrl(d.url) : d?.filename ? generatedFileUrl(d.filename) : "";
              if (!src) return null;
              return (
                <img
                  key={`${draft.question_id}-diagram-${i}`}
                  src={src}
                  alt={d?.alt || d?.caption || "题目配图"}
                  className="h-20 w-auto rounded-md border border-border object-contain"
                  loading="lazy"
                />
              );
            })}
          </div>
        ) : null}

        <Accordion type="single" collapsible>
          <AccordionItem value="detail" className="border-b-0">
            <AccordionTrigger className="py-2 text-xs text-muted-foreground">
              查看答案与解析
            </AccordionTrigger>
            <AccordionContent>
              <div className="space-y-3 rounded-lg bg-muted/50 p-3">
                <div>
                  {sectionHeader("答案", "answer")}
                  {sectionBody("answer", draft.answer)}
                </div>
                <div>
                  {sectionHeader("解析", "analysis")}
                  {sectionBody("analysis", draft.analysis)}
                </div>
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>

        {review ? (
          <div className="space-y-2 rounded-lg border border-border p-3">
            <div className="text-xs font-medium text-muted-foreground">AI 评审</div>
            {Array.isArray(review.dimensions) && review.dimensions.length > 0 ? (
              <div className="space-y-1.5">
                {review.dimensions.map((dim, i) => (
                  <div key={`${dim.name}-${i}`} className="flex items-center gap-2 text-xs">
                    <span className="w-24 shrink-0 truncate text-muted-foreground" title={dim.comment || dim.name}>
                      {dim.name || `维度 ${i + 1}`}
                    </span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary"
                        style={{ width: `${clamp(Number(dim.score) || 0, 0, 100)}%` }}
                      />
                    </div>
                    <span className="w-8 shrink-0 text-right tabular-nums">{dim.score}</span>
                  </div>
                ))}
              </div>
            ) : null}
            {Array.isArray(review.highlights) && review.highlights.length > 0 ? (
              <ul className="space-y-0.5 text-xs text-success">
                {review.highlights.map((h, i) => (
                  <li key={`h-${i}`}>· {h}</li>
                ))}
              </ul>
            ) : null}
            {Array.isArray(review.issues) && review.issues.length > 0 ? (
              <ul className="space-y-0.5 text-xs text-destructive">
                {review.issues.map((s, i) => (
                  <li key={`i-${i}`}>· {s}</li>
                ))}
              </ul>
            ) : null}
            {review.summary ? <p className="text-xs text-muted-foreground">{review.summary}</p> : null}
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">暂无评审信息</div>
        )}
      </div>
    </Card>
  );
}

function PreviewReview({ preview, onExit }: { preview: LibraryPreview; onExit: (committed: boolean) => void }) {
  const toast = useUiStore((s) => s.toast);
  const [drafts, setDrafts] = useState<DraftQuestion[]>(() =>
    (preview.draft_questions ?? []).map((d) => ({
      ...d,
      keep: d.review ? Number(d.review.overall_score ?? 0) >= 60 : true,
    })),
  );
  const [regenKey, setRegenKey] = useState<string | null>(null);
  const regenAbort = useRef<AbortController | null>(null);
  const [commitOpen, setCommitOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);

  const kept = drafts.filter((d) => d.keep !== false);

  const setKeep = (qid: string, keep: boolean) =>
    setDrafts((ds) => ds.map((d) => (d.question_id === qid ? { ...d, keep } : d)));

  const regenerate = (qid: string, section: SectionKey) => {
    regenAbort.current?.abort();
    const controller = new AbortController();
    regenAbort.current = controller;
    const key = `${qid}:${section}`;
    setRegenKey(key);
    libraryApi.regenerateSection(
      preview.preview_id,
      { question_id: qid, section_key: section },
      {
        signal: controller.signal,
        onEvent: (ev) => {
          if (ev.type === "done" || ev.type === "result") {
            // done 携带权威 draft_question：内容实际变化时后端已剔除过期 review 并置
            // pending_review；未变化时保留原评审——前端整体采纳，不手动清空
            const updated = ev.data?.draft_question as DraftQuestion | undefined;
            const content = typeof ev.data?.content === "string" ? ev.data.content : "";
            setDrafts((ds) =>
              ds.map((d) => {
                if (d.question_id !== qid) return d;
                if (updated && typeof updated === "object") return { ...updated, keep: d.keep };
                return content ? { ...d, [section]: content } : d;
              }),
            );
            toast({ title: "已重新生成", description: "该节内容已更新", variant: "success" });
          } else if (ev.type === "error") {
            toast({
              title: "重新生成失败",
              description: String(ev.data?.message || ev.data?.error || "请稍后重试"),
              variant: "destructive",
            });
          }
        },
        onDone: () => {
          setRegenKey((k) => (k === key ? null : k));
        },
        onError: (err) => {
          setRegenKey((k) => (k === key ? null : k));
          toast({ title: "重新生成失败", description: err.message || "请稍后重试", variant: "destructive" });
        },
      },
    );
  };

  const commitMut = useMutation({
    mutationFn: () =>
      libraryApi.commitPreview(
        preview.preview_id,
        kept.map((d) => ({ ...d, keep: true })),
      ),
    onSuccess: (res) => {
      toast({ title: "入库成功", description: `已入库 ${res?.inserted ?? kept.length} 题`, variant: "success" });
      setCommitOpen(false);
      onExit(true);
    },
    onError: (err) => toast({ title: "入库失败", description: apiErrorText(err, "请稍后重试"), variant: "destructive" }),
  });

  const discardMut = useMutation({
    mutationFn: () => libraryApi.discardPreview(preview.preview_id),
    onSuccess: () => {
      toast({ title: "已放弃预览", description: "草稿已丢弃，不会写入题库" });
      setDiscardOpen(false);
      onExit(false);
    },
    onError: (err) => toast({ title: "操作失败", description: apiErrorText(err, "请稍后重试"), variant: "destructive" }),
  });

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" className="-ml-2" onClick={() => onExit(false)}>
            <ArrowLeft />
            返回题库
          </Button>
          <div>
            <h2 className="text-lg font-semibold tracking-tight">预览审核</h2>
            <p className="text-xs text-muted-foreground">
              {[preview.subject, preview.topic, preview.difficulty, preview.question_type]
                .filter(Boolean)
                .join(" · ") || "未命名预览"}
            </p>
          </div>
        </div>
        <Badge variant="warning">待审核 {drafts.length} 题</Badge>
      </div>

      {drafts.length === 0 ? (
        <EmptyState title="预览中没有草稿" description="该预览可能已被处理，返回题库后可重新发起出题" />
      ) : (
        <div className="space-y-4 pb-20">
          {drafts.map((d, i) => (
            <DraftCard
              key={d.question_id || i}
              index={i}
              draft={d}
              regenKey={regenKey}
              onToggleKeep={(checked) => setKeep(d.question_id, checked)}
              onRegenerate={(section) => regenerate(d.question_id, section)}
            />
          ))}
        </div>
      )}

      {drafts.length > 0 ? (
        <div className="sticky bottom-4 z-20 flex items-center justify-between gap-3 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-lift backdrop-blur">
          <span className="text-sm text-muted-foreground">
            已勾选 {kept.length} / 共 {drafts.length} 题
          </span>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setDiscardOpen(true)}>
              放弃预览
            </Button>
            <Button onClick={() => setCommitOpen(true)} disabled={kept.length === 0}>
              提交入库
            </Button>
          </div>
        </div>
      ) : null}

      <Dialog open={commitOpen} onOpenChange={setCommitOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>提交入库</DialogTitle>
            <DialogDescription>将把勾选的 {kept.length} 道题写入本地题库，未勾选的题目将被丢弃。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCommitOpen(false)}>
              取消
            </Button>
            <Button disabled={commitMut.isPending || kept.length === 0} onClick={() => commitMut.mutate()}>
              {commitMut.isPending ? <Spinner className="text-primary-foreground" /> : null}
              确认入库
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={discardOpen} onOpenChange={setDiscardOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>放弃预览</DialogTitle>
            <DialogDescription>将丢弃全部 {drafts.length} 道草稿，此操作不可撤销。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDiscardOpen(false)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={discardMut.isPending}
              onClick={() => discardMut.mutate()}
            >
              {discardMut.isPending ? <Spinner className="text-destructive-foreground" /> : null}
              确认放弃
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------- 页面 ----------------

export function LibraryPage() {
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);
  // tab 入 URL（架构 §8.4）：/library?tab=generate 可直达
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseEnumParam(searchParams, "tab", ["browse", "generate", "crawl"] as const) ?? "browse";
  const setTab = (v: string) =>
    setSearchParams((prev) => updateSearchParams(prev, { tab: v === "browse" ? null : v }), { replace: true });
  const [preview, setPreview] = useState<LibraryPreview | null>(null);
  const [resuming, setResuming] = useState(false);

  const pendingQuery = useQuery({
    queryKey: ["library-latest-pending-preview"],
    queryFn: () => libraryApi.latestPendingPreview(),
    staleTime: 15_000,
  });
  const pending = pendingQuery.data?.preview ?? null;

  const resumePending = async () => {
    if (!pending?.preview_id) return;
    setResuming(true);
    try {
      const pv = await libraryApi.preview(pending.preview_id);
      setPreview(pv);
    } catch (err) {
      toast({ title: "恢复预览失败", description: apiErrorText(err, "请稍后重试"), variant: "destructive" });
    } finally {
      setResuming(false);
    }
  };

  const exitPreview = (committed: boolean) => {
    setPreview(null);
    queryClient.invalidateQueries({ queryKey: ["library-latest-pending-preview"] });
    if (committed) queryClient.invalidateQueries({ queryKey: ["library-items"] });
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <LibraryBig className="size-5 text-primary" />
          题库
        </h1>
        <p className="text-sm text-muted-foreground">浏览本地题库、AI 出题审核入库、抓取与评分清洗</p>
      </header>

      {pending && !preview ? (
        <Alert variant="info">
          <History />
          <AlertTitle>有未完成的出题预览</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>
              {[pending.subject, pending.topic].filter(Boolean).join(" · ") || "未命名"}（
              {pending.draft_count ?? pending.draft_questions?.length ?? 0} 题待审核）
            </span>
            <Button size="sm" variant="outline" onClick={resumePending} disabled={resuming}>
              {resuming ? <Spinner /> : null}
              恢复审核
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {preview ? (
        <PreviewReview key={preview.preview_id} preview={preview} onExit={exitPreview} />
      ) : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="browse">题库浏览</TabsTrigger>
            <TabsTrigger value="generate">AI 出题</TabsTrigger>
            <TabsTrigger value="crawl">抓取与评分</TabsTrigger>
          </TabsList>
          <TabsContent value="browse">
            <BrowsePanel onGoGenerate={() => setTab("generate")} />
          </TabsContent>
          <TabsContent value="generate">
            <GeneratePanel onPreview={setPreview} />
          </TabsContent>
          <TabsContent value="crawl">
            <CrawlScorePanel />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
