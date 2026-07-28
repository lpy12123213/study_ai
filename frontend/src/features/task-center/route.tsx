import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronRight,
  CircleStop,
  ClipboardCheck,
  Download,
  FileArchive,
  Files,
  ListChecks,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
} from "lucide-react";

import { ApiError, downloadUrl } from "@/shared/api/http-client";
import { exportsApi, tasksApi, type TaskDetail } from "@/features/task-center/api";
import {
  TASK_STATUS_LABELS,
  TASK_TYPE_LABELS,
  type TaskEvent,
  type TaskStatus,
  type TaskSummary,
} from "@/shared/api/types";
import { clamp, formatBytes, formatDateTime, formatDuration, formatRelative, parseBackendDate } from "@/lib/format";
import { generatedFileUrl } from "@/lib/media";
import { parseEnumParam, parseStringParam, updateSearchParams } from "@/shared/lib/search-params";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";
import { MarkdownView } from "@/components/markdown/markdown-view";
import { TaskProgressPanel } from "@/components/task/task-progress-panel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

/**
 * 任务中心 · Task Master-Detail（视觉规划 §5.3）。
 * - 左列：状态/类型筛选 + 高密度任务列表；右列：所选任务的阶段、事件、人工审核与结果；
 * - tab（tasks/exports）、status、type、选中任务均入 URL，可分享可恢复（架构 §8.4）；
 * - 状态轨道复用与对话时间线相同的视觉语言，但消费持久任务投影（tasks store / Coordinator）。
 */

const STATUS_FILTERS = ["running", "paused", "pending_review", "completed", "failed", "canceled"] as const;
const TAB_VALUES = ["tasks", "exports"] as const;

function truncateId(id: string): string {
  const s = String(id || "");
  return s.length > 18 ? `${s.slice(0, 10)}…${s.slice(-6)}` : s;
}

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

type StatusBadgeVariant = "default" | "success" | "destructive" | "warning" | "muted";

function statusBadgeVariant(status: string): StatusBadgeVariant {
  switch (status) {
    case "completed":
      return "success";
    case "failed":
      return "destructive";
    case "pending_review":
      return "warning";
    case "running":
      return "default";
    default:
      return "muted"; // paused / canceled
  }
}

/**
 * 把任务详情（DB 版 events / 内存版 steps）回填进全局 tasks store。
 * 按 seq 去重保证幂等（重复展开不会重复拼接 text_delta）。
 */
function backfillDetail(taskId: string, detail: TaskDetail) {
  const store = useTasksStore.getState();
  const type = String(detail.task_type ?? detail.type ?? "");
  const title = typeof detail.title === "string" ? detail.title : "";
  store.register(taskId, { type, title });

  const seenSeq = useTasksStore.getState().active[taskId]?.lastSeq ?? 0;
  const events = Array.isArray(detail.events) ? detail.events : [];
  for (const raw of events) {
    if (!raw || typeof raw !== "object") continue;
    const seq = typeof raw.seq === "number" ? raw.seq : 0;
    if (seq > 0 && seq <= seenSeq) continue; // 幂等：跳过已回放的历史事件
    const ev: TaskEvent = {
      type: typeof raw.type === "string" ? raw.type : "event",
      data: raw.data && typeof raw.data === "object" ? raw.data : {},
      seq,
      taskId,
      raw,
    };
    store.applyEvent(taskId, ev);
  }

  // 内存版详情没有 events，仅有 steps 快照（step 事件按 id 合并，天然幂等）
  if (events.length === 0 && Array.isArray(detail.steps)) {
    for (const step of detail.steps) {
      store.applyEvent(taskId, { type: "step", data: { step }, seq: 0, taskId });
    }
  }

  if (typeof detail.progress === "number") {
    store.applyEvent(taskId, { type: "progress", data: { progress: detail.progress }, seq: 0, taskId });
  }

  const result = detail.result;
  const current = useTasksStore.getState().active[taskId];
  if (current && current.result === undefined && result && typeof result === "object" && Object.keys(result).length > 0) {
    store.applyEvent(taskId, { type: "result", data: { result }, seq: 0, taskId });
  }

  const status = String(detail.status ?? "") as TaskStatus;
  const isCanceled = status === "canceled" || status === "cancelled";

  const errPayload = detail.error;
  const errMsg =
    typeof errPayload === "string"
      ? errPayload
      : errPayload && typeof errPayload === "object"
        ? String(errPayload.message ?? errPayload.error ?? "")
        : "";
  const afterResult = useTasksStore.getState().active[taskId];
  // 取消的任务后端也会写 error（"Task cancelled"）——不应当作失败回填
  if (errMsg && afterResult && !afterResult.error && !isCanceled) {
    store.applyEvent(taskId, { type: "error", data: { error: errMsg }, seq: 0, taskId });
  }

  if (status === "pending_review") {
    const draftEvent = [...events]
      .reverse()
      .find((e) => e && typeof e === "object" && e.data && typeof e.data === "object" && e.data.composeDraft);
    const draft = (result && typeof result === "object" ? result.composeDraft : undefined) ?? draftEvent?.data?.composeDraft;
    store.applyEvent(taskId, { type: "pending_review", data: { composeDraft: draft }, seq: 0, taskId });
  }
  if (status) store.setStatus(taskId, status);
}

/** 导出文件过期状态。 */
function expiryFlag(expiresAt?: string): "none" | "ok" | "soon" | "expired" {
  const raw = String(expiresAt ?? "").trim();
  if (!raw) return "none";
  const d = parseBackendDate(raw);
  if (!d) return "expired";
  const t = d.getTime();
  const now = Date.now();
  if (t <= now) return "expired";
  if (t - now <= 3600_000) return "soon";
  return "ok";
}

function DetailSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-border bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-left text-sm font-medium"
      >
        <ChevronRight className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
        {title}
      </button>
      {open ? <div className="border-t border-border px-4 py-3">{children}</div> : null}
    </div>
  );
}

interface TaskActions {
  busy: boolean;
  onPause: (taskId: string) => void;
  onResume: (taskId: string) => void;
  onRetry: (taskId: string) => void;
  onCancel: (task: { id: string; title?: string }) => void;
}

/** 右侧详情：概要头（状态 + 操作）→ 实时进度轨道 → 审核/失败提示 → 输出内容。 */
function TaskDetailPanel({
  taskId,
  summary,
  actions,
}: {
  taskId: string;
  summary?: TaskSummary;
  actions: TaskActions;
}) {
  const live = useTasksStore((s) => s.active[taskId]);
  const status = (live?.status ?? summary?.status ?? "running") as TaskStatus;
  const taskType = summary?.task_type ?? live?.type ?? "";
  const title = summary?.title?.trim() || live?.title?.trim() || truncateId(taskId);
  const isComposeReview = taskType === "paper_compose" && status === "pending_review";
  const progress = clamp(live?.progress ?? summary?.progress ?? 0, 0, 100);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-3 border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          {taskType ? <Badge variant="secondary">{TASK_TYPE_LABELS[taskType] ?? taskType}</Badge> : null}
          <span className="min-w-0 flex-1 truncate text-sm font-semibold" title={title}>
            {title}
          </span>
          <Badge variant={statusBadgeVariant(status)}>{TASK_STATUS_LABELS[status] ?? status}</Badge>
        </div>
        <div className="flex items-center gap-3">
          <Progress value={progress} className="flex-1" />
          <span className="w-9 text-right text-xs tabular-nums text-muted-foreground">{Math.round(progress)}%</span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-mono text-[11px] text-muted-foreground" title={taskId}>
            {truncateId(taskId)}
            {summary?.created_at ? ` · ${formatRelative(summary.created_at)}` : ""}
            {typeof summary?.elapsed_s === "number" ? ` · 已用 ${formatDuration(summary.elapsed_s)}` : ""}
          </span>
          {/* 关键操作固定在详情区附近（Master-Detail），不散落在列表行 */}
          <div className="flex flex-wrap items-center gap-1.5">
            {status === "running" ? (
              <>
                <Button size="sm" variant="outline" disabled={actions.busy} onClick={() => actions.onPause(taskId)}>
                  <Pause />
                  暂停
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                  disabled={actions.busy}
                  onClick={() => actions.onCancel({ id: taskId, title })}
                >
                  <CircleStop />
                  取消
                </Button>
              </>
            ) : null}
            {status === "paused" ? (
              <>
                <Button size="sm" variant="outline" disabled={actions.busy} onClick={() => actions.onResume(taskId)}>
                  <Play />
                  恢复
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-destructive hover:text-destructive"
                  disabled={actions.busy}
                  onClick={() => actions.onCancel({ id: taskId, title })}
                >
                  <CircleStop />
                  取消
                </Button>
              </>
            ) : null}
            {status === "failed" ? (
              <Button size="sm" variant="outline" disabled={actions.busy} onClick={() => actions.onRetry(taskId)}>
                <RotateCcw />
                重试
              </Button>
            ) : null}
            {isComposeReview ? (
              <Button size="sm" asChild>
                <Link to="/compose">
                  <ClipboardCheck />
                  去审核
                </Link>
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <TaskProgressPanel taskId={taskId} />

        {live?.error ? (
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertTitle>任务失败</AlertTitle>
            <AlertDescription>{live.error}</AlertDescription>
          </Alert>
        ) : null}

        {isComposeReview ? (
          <Alert variant="warning">
            <ClipboardCheck />
            <AlertTitle>等待人工审核</AlertTitle>
            <AlertDescription>
              请前往组卷工作室完成人工审核。
              <Button asChild variant="link" size="sm" className="ml-1 h-auto p-0 align-baseline">
                <Link to="/compose">去审核</Link>
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {live?.text ? (
          <DetailSection title="输出内容" defaultOpen>
            <div className="max-h-80 overflow-y-auto">
              <MarkdownView content={live.text} />
            </div>
          </DetailSection>
        ) : null}

        {live?.reasoning ? (
          <DetailSection title="推理过程">
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-xs text-muted-foreground">
              {live.reasoning}
            </pre>
          </DetailSection>
        ) : null}

        {live && live.result !== undefined && live.result !== null ? (
          <DetailSection title="结果 JSON">
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-xs text-muted-foreground">
              {JSON.stringify(live.result, null, 2)}
            </pre>
          </DetailSection>
        ) : null}
      </div>
    </div>
  );
}

function TaskRow({
  task,
  active,
  onSelect,
}: {
  task: TaskSummary;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "block w-full border-b border-border px-3 py-2.5 text-left transition-colors last:border-b-0",
        active ? "bg-accent text-accent-foreground" : "hover:bg-muted/60",
      )}
    >
      <div className="flex items-center gap-2">
        <Badge variant="secondary" className="shrink-0">
          {TASK_TYPE_LABELS[task.task_type] ?? task.task_type}
        </Badge>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{task.title?.trim() || truncateId(task.id)}</span>
        <Badge variant={statusBadgeVariant(task.status)} className="shrink-0">
          {TASK_STATUS_LABELS[task.status] ?? task.status}
        </Badge>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <Progress value={clamp(task.progress ?? 0, 0, 100)} className="h-1.5 flex-1" />
        <span className="w-9 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
          {Math.round(clamp(task.progress ?? 0, 0, 100))}%
        </span>
        <span className="shrink-0 text-[11px] text-muted-foreground">{formatRelative(task.created_at)}</span>
      </div>
    </button>
  );
}

function TasksMasterDetail() {
  const toast = useUiStore((s) => s.toast);
  const queryClient = useQueryClient();
  const isDesktop = useMediaQuery("(min-width: 1024px)");

  const [searchParams, setSearchParams] = useSearchParams();
  const statusFilter = parseEnumParam(searchParams, "status", STATUS_FILTERS) ?? "all";
  const typeFilter = parseStringParam(searchParams, "type") ?? "all";
  const selectedTaskId = parseStringParam(searchParams, "task") ?? null;
  const [cancelTarget, setCancelTarget] = useState<{ id: string; title?: string } | null>(null);

  const patchParams = (patch: Record<string, string | null | undefined>, replace = true) =>
    setSearchParams((prev) => updateSearchParams(prev, patch), { replace });

  const tasksQuery = useQuery({
    queryKey: ["tasks", statusFilter, typeFilter],
    queryFn: () =>
      tasksApi.list({
        status: statusFilter === "all" ? undefined : statusFilter,
        type: typeFilter === "all" ? undefined : typeFilter,
        limit: 50,
        offset: 0,
      }),
    refetchInterval: (query) => {
      const tasks = query.state.data?.tasks;
      return tasks && tasks.some((t) => t.status === "running" || t.status === "paused") ? 3000 : false;
    },
  });
  const tasks = useMemo(() => tasksQuery.data?.tasks ?? [], [tasksQuery.data]);
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;

  const selectedSummary = tasks.find((t) => t.id === selectedTaskId);

  // 选中任务变化：注册 → 拉取详情回填 → 打开事件流（Coordinator 负责重连与校准）
  useEffect(() => {
    if (!selectedTaskId) return;
    let disposed = false;
    const summary = tasksRef.current.find((t) => t.id === selectedTaskId);
    const meta = summary ? { type: summary.task_type, title: summary.title ?? "" } : undefined;
    useTasksStore.getState().register(selectedTaskId, meta);
    void (async () => {
      try {
        const detail = await tasksApi.get(selectedTaskId, { includeEvents: true, eventsLimit: 200 });
        if (!disposed) backfillDetail(selectedTaskId, detail);
      } catch {
        // 详情拉取失败不阻塞：任务流续播仍可能补齐数据
      }
      if (!disposed) useTasksStore.getState().watch(selectedTaskId, meta);
    })();
    return () => {
      disposed = true;
    };
  }, [selectedTaskId]);

  const refreshTasks = () => queryClient.invalidateQueries({ queryKey: ["tasks"] });

  const pauseMut = useMutation({
    mutationFn: (taskId: string) => tasksApi.pause(taskId),
    onSuccess: (_data, taskId) => {
      useTasksStore.getState().setStatus(taskId, "paused");
      toast({ title: "任务已暂停", variant: "success" });
      void refreshTasks();
    },
    onError: (err) => toast({ title: "暂停失败", description: errText(err, "请稍后重试"), variant: "destructive" }),
  });

  const resumeMut = useMutation({
    mutationFn: async (taskId: string) => {
      try {
        await tasksApi.resume(taskId);
        return { retried: false, newTaskId: "" };
      } catch (err) {
        if (err instanceof ApiError && err.status === 409 && err.code === "task_runner_unavailable") {
          const res = await tasksApi.retry(taskId);
          return { retried: true, newTaskId: res.taskId };
        }
        throw err;
      }
    },
    onSuccess: (r, taskId) => {
      if (r.retried) {
        toast({ title: "运行器不可用，已转为重试", description: "已创建新任务继续执行", variant: "warning" });
        useTasksStore.getState().register(r.newTaskId);
        useTasksStore.getState().watch(r.newTaskId);
        patchParams({ task: r.newTaskId }, false);
      } else {
        useTasksStore.getState().setStatus(taskId, "running");
        useTasksStore.getState().watch(taskId);
        toast({ title: "任务已恢复", variant: "success" });
      }
      void refreshTasks();
    },
    onError: (err) => toast({ title: "恢复失败", description: errText(err, "请稍后重试"), variant: "destructive" }),
  });

  const retryMut = useMutation({
    mutationFn: (taskId: string) => tasksApi.retry(taskId),
    onSuccess: (res) => {
      toast({ title: "已创建新任务", description: `新任务 ${truncateId(res.taskId)} 已开始执行`, variant: "success" });
      useTasksStore.getState().register(res.taskId);
      useTasksStore.getState().watch(res.taskId);
      patchParams({ task: res.taskId }, false);
      void refreshTasks();
    },
    onError: (err) =>
      toast({ title: "重试失败", description: errText(err, "该任务类型可能不支持重试"), variant: "destructive" }),
  });

  const cancelMut = useMutation({
    mutationFn: (taskId: string) => tasksApi.cancel(taskId),
    onSuccess: (_data, taskId) => {
      useTasksStore.getState().setStatus(taskId, "canceled");
      toast({ title: "任务已取消", variant: "success" });
      setCancelTarget(null);
      void refreshTasks();
    },
    onError: (err) => toast({ title: "取消失败", description: errText(err, "请稍后重试"), variant: "destructive" }),
  });

  const actions: TaskActions = {
    busy: pauseMut.isPending || resumeMut.isPending || retryMut.isPending || cancelMut.isPending,
    onPause: (id) => pauseMut.mutate(id),
    onResume: (id) => resumeMut.mutate(id),
    onRetry: (id) => retryMut.mutate(id),
    onCancel: setCancelTarget,
  };

  const detail = selectedTaskId ? (
    <TaskDetailPanel
      taskId={selectedTaskId}
      {...(selectedSummary ? { summary: selectedSummary } : {})}
      actions={actions}
    />
  ) : (
    <EmptyState
      icon={ListChecks}
      title="选择一个任务"
      description="在左侧选择任务查看实时进度、事件时间线、人工审核与结果"
    />
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 lg:flex-row">
      {/* 左列：筛选 + 高密度任务列表 */}
      <section
        aria-label="任务列表"
        className="flex min-h-0 w-full flex-col overflow-hidden rounded-xl border border-border bg-card shadow-soft lg:w-[380px] lg:shrink-0"
      >
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border p-3">
          <Select value={statusFilter} onValueChange={(v) => patchParams({ status: v === "all" ? null : v })}>
            <SelectTrigger className="h-8 w-[124px] text-xs">
              <SelectValue placeholder="全部状态" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {STATUS_FILTERS.map((s) => (
                <SelectItem key={s} value={s}>
                  {TASK_STATUS_LABELS[s] ?? s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={typeFilter} onValueChange={(v) => patchParams({ type: v === "all" ? null : v })}>
            <SelectTrigger className="h-8 min-w-0 flex-1 text-xs">
              <SelectValue placeholder="全部类型" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部类型</SelectItem>
              {Object.entries(TASK_TYPE_LABELS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="刷新任务列表"
            onClick={() => void tasksQuery.refetch()}
            disabled={tasksQuery.isFetching}
          >
            <RefreshCw className={cn(tasksQuery.isFetching && "animate-spin")} />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {tasksQuery.isLoading ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : tasksQuery.isError ? (
            <div className="p-3">
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertTitle>加载失败</AlertTitle>
                <AlertDescription>{errText(tasksQuery.error, "无法获取任务列表，请稍后重试")}</AlertDescription>
              </Alert>
            </div>
          ) : tasks.length === 0 ? (
            <EmptyState
              icon={ListChecks}
              title="暂无任务"
              description="当前筛选条件下没有任务；从组卷、学习资料或题库等功能发起的长任务会出现在这里。"
            />
          ) : (
            <div role="list">
              {tasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  active={task.id === selectedTaskId}
                  onSelect={() => patchParams({ task: task.id }, false)}
                />
              ))}
            </div>
          )}
        </div>
      </section>

      {/* 右列（≥1024px 常驻）：所选任务详情；窄屏在列表下方堆叠 */}
      {isDesktop || selectedTaskId ? (
        <section
          aria-label="任务详情"
          className="min-h-0 min-w-0 flex-1 overflow-hidden rounded-xl border border-border bg-card shadow-soft"
        >
          {detail}
        </section>
      ) : null}

      <Dialog open={cancelTarget !== null} onOpenChange={(open) => (!open ? setCancelTarget(null) : undefined)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>取消任务</DialogTitle>
            <DialogDescription>
              确定要取消任务「{cancelTarget ? cancelTarget.title?.trim() || truncateId(cancelTarget.id) : ""}
              」吗？进行中的进度将丢失，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCancelTarget(null)}>
              再想想
            </Button>
            <Button
              variant="destructive"
              disabled={cancelMut.isPending}
              onClick={() => (cancelTarget ? cancelMut.mutate(cancelTarget.id) : undefined)}
            >
              {cancelMut.isPending ? <Spinner className="text-destructive-foreground" /> : null}
              确认取消
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ExportsTab() {
  const toast = useUiStore((s) => s.toast);
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const filesQuery = useQuery({
    queryKey: ["export-files"],
    queryFn: () => exportsApi.files({ limit: 100 }),
  });
  const files = filesQuery.data?.files ?? [];

  const selectedNames = files.filter((f) => selected.has(f.filename)).map((f) => f.filename);
  const allChecked = files.length > 0 && selectedNames.length === files.length;
  const someChecked = selectedNames.length > 0;

  const toggleAll = () => {
    setSelected(allChecked ? new Set() : new Set(files.map((f) => f.filename)));
  };
  const toggleOne = (name: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(name);
      else next.delete(name);
      return next;
    });
  };

  const zipMut = useMutation({
    mutationFn: (filenames: string[]) => exportsApi.zip(filenames),
    onSuccess: (res) => {
      const url = downloadUrl(res.url);
      if (url) window.open(url, "_blank");
      toast({ title: "ZIP 已生成", description: `${res.filename}（${formatBytes(res.bytes)}）`, variant: "success" });
      setSelected(new Set());
      // 后端 zip 也落 generated_files——刷新列表让新 zip 立即可见
      void queryClient.invalidateQueries({ queryKey: ["export-files"] });
    },
    onError: (err) => toast({ title: "打包失败", description: errText(err, "请稍后重试"), variant: "destructive" }),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-sm text-muted-foreground">
          已选 <span className="font-medium tabular-nums text-foreground">{selectedNames.length}</span> 个文件
        </div>
        <Button
          size="sm"
          disabled={selectedNames.length === 0 || zipMut.isPending}
          onClick={() => zipMut.mutate(selectedNames)}
        >
          {zipMut.isPending ? <Spinner className="text-primary-foreground" /> : <FileArchive />}
          打包下载 ZIP
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => void filesQuery.refetch()}
          disabled={filesQuery.isFetching}
        >
          <RefreshCw className={cn(filesQuery.isFetching && "animate-spin")} />
          刷新
        </Button>
      </div>

      {filesQuery.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full rounded-xl" />
          ))}
        </div>
      ) : filesQuery.isError ? (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>加载失败</AlertTitle>
          <AlertDescription>{errText(filesQuery.error, "无法获取导出文件列表，请稍后重试")}</AlertDescription>
        </Alert>
      ) : files.length === 0 ? (
        <EmptyState
          icon={Files}
          title="暂无导出文件"
          description="试卷或学习资料导出后会生成可下载文件；下载链接有时效，过期后需重新导出。"
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-soft">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="w-10 px-4 py-3">
                  <Checkbox
                    checked={allChecked ? true : someChecked ? "indeterminate" : false}
                    onCheckedChange={toggleAll}
                    aria-label="全选"
                  />
                </th>
                <th className="px-4 py-3 font-medium">文件名</th>
                <th className="px-4 py-3 font-medium">类型</th>
                <th className="px-4 py-3 font-medium">大小</th>
                <th className="px-4 py-3 font-medium">创建时间</th>
                <th className="px-4 py-3 font-medium">过期时间</th>
                <th className="w-16 px-4 py-3 text-right font-medium">下载</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => {
                const expiry = expiryFlag(f.expires_at);
                const expiryWarn = expiry === "soon" || expiry === "expired";
                return (
                  <tr key={f.filename} className="border-b border-border last:border-0 hover:bg-muted/40">
                    <td className="px-4 py-3">
                      <Checkbox
                        checked={selected.has(f.filename)}
                        onCheckedChange={(c) => toggleOne(f.filename, c === true)}
                        aria-label={`选择 ${f.filename}`}
                      />
                    </td>
                    <td className="max-w-64 px-4 py-3">
                      <span className="block truncate font-mono text-xs" title={f.filename}>
                        {f.filename}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="muted">{f.file_type || "file"}</Badge>
                    </td>
                    <td className="px-4 py-3 text-xs tabular-nums text-muted-foreground">{formatBytes(f.bytes)}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">{formatDateTime(f.created_at)}</td>
                    <td className={cn("px-4 py-3 text-xs", expiryWarn ? "text-warning" : "text-muted-foreground")}>
                      {expiry === "none" ? "长期有效" : formatDateTime(f.expires_at)}
                      {expiry === "expired" ? "（已过期）" : expiry === "soon" ? "（即将过期）" : ""}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Button asChild variant="ghost" size="icon-sm" title="下载文件">
                        <a href={generatedFileUrl(f.filename)} target="_blank" rel="noreferrer" download={f.filename}>
                          <Download />
                        </a>
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function TaskCenterPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseEnumParam(searchParams, "tab", TAB_VALUES) ?? "tasks";

  return (
    <div className="flex h-full min-h-0 animate-fade-in flex-col gap-4 p-4">
      <Tabs
        value={tab}
        onValueChange={(v) =>
          setSearchParams((prev) => updateSearchParams(prev, { tab: v === "tasks" ? null : v }), { replace: true })
        }
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="shrink-0 self-start">
          <TabsTrigger value="tasks">
            <ListChecks />
            任务列表
          </TabsTrigger>
          <TabsTrigger value="exports">
            <Files />
            导出文件
          </TabsTrigger>
        </TabsList>
        <TabsContent value="tasks" className="min-h-0 flex-1">
          <TasksMasterDetail />
        </TabsContent>
        <TabsContent value="exports" className="min-h-0 flex-1 overflow-y-auto">
          <ExportsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
