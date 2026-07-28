import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpenText,
  CircleCheck,
  FileDown,
  FileStack,
  Files,
  ListTodo,
  MessagesSquare,
  Sparkles,
  Timer,
  type LucideIcon,
} from "lucide-react";

import { ApiError } from "@/shared/api/http-client";
import { conversationsApi } from "@/features/chat/api";
import { studyArchivesApi } from "@/features/study-materials/api";
import { papersApi } from "@/features/paper-library/api";
import { systemApi } from "@/shared/api/system";
import { tasksApi } from "@/features/task-center/api";
import {
  TASK_STATUS_LABELS,
  TASK_TYPE_LABELS,
  type HealthStatus,
} from "@/shared/api/types";
import { clamp, formatDuration, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { PromptComposer } from "@/features/chat/ui/prompt-composer";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";

// ---------------- 欢迎区 / 健康状态 ----------------

type HealthLevel = "healthy" | "degraded" | "unhealthy" | "unknown";

interface HealthView {
  level: HealthLevel;
  failed: string[];
}

const HEALTH_META: Record<HealthLevel, { label: string; dot: string; text: string }> = {
  healthy: { label: "服务正常", dot: "bg-success", text: "text-success" },
  degraded: { label: "服务降级", dot: "bg-warning", text: "text-warning" },
  unhealthy: { label: "服务异常", dot: "bg-destructive", text: "text-destructive" },
  unknown: { label: "状态未知", dot: "bg-muted-foreground/40", text: "text-muted-foreground" },
};

function collectFailedChecks(checks?: HealthStatus["checks"]): string[] {
  const failed: string[] = [];
  if (!checks) return failed;
  if (checks.db && checks.db.ok === false) failed.push("数据库连接异常");
  if (checks.disk && checks.disk.ok === false) failed.push("磁盘空间不足");
  const llm = checks.llm;
  if (llm && (llm.ok === false || llm.status === "warn" || llm.configured === false)) {
    failed.push("模型服务未配置");
  }
  return failed;
}

/** 健康检查静默获取：unhealthy 时后端返回 503，payload 在 ApiError.details 里。 */
async function fetchHealth(): Promise<HealthView> {
  try {
    const res = await systemApi.health();
    const level: HealthLevel =
      res.status === "healthy" || res.status === "degraded" || res.status === "unhealthy"
        ? res.status
        : "unknown";
    return { level, failed: collectFailedChecks(res.checks) };
  } catch (err) {
    if (err instanceof ApiError) {
      const details = err.details as { checks?: HealthStatus["checks"] } | undefined;
      if (details && typeof details === "object" && details.checks) {
        return { level: "unhealthy", failed: collectFailedChecks(details.checks) };
      }
    }
    return { level: "unknown", failed: [] };
  }
}

function greetingForHour(hour: number): string {
  if (hour < 6) return "夜深了";
  if (hour < 12) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

// ---------------- Intent Workspace ----------------

type IntentTarget = "chat" | "compose" | "materials" | "deepthink";

const INTENT_MODES: { id: IntentTarget; label: string; icon: LucideIcon; hint: string }[] = [
  { id: "chat", label: "对话", icon: MessagesSquare, hint: "问答与讲解" },
  { id: "compose", label: "组卷", icon: FileStack, hint: "拼组试卷" },
  { id: "materials", label: "学习资料", icon: BookOpenText, hint: "生成讲义" },
  { id: "deepthink", label: "DeepThink", icon: Sparkles, hint: "深度推理" },
];

const INTENT_PLACEHOLDERS: Record<IntentTarget, string> = {
  chat: "输入想问的问题，Enter 开始对话",
  compose: "描述想要的试卷（如：高一数学三角函数中等难度），Enter 前往组卷",
  materials: "输入想学的主题（如：牛顿第二定律），Enter 前往生成资料",
  deepthink: "输入需要深度推理的题目，Enter 前往 DeepThink",
};

// ---------------- 页面 ----------------

export function HomePage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  const now = new Date();
  const dateText = new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(now);

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    retry: false,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
  const health = healthQuery.data;
  const healthMeta = HEALTH_META[health?.level ?? "unknown"];

  const statsQuery = useQuery({
    queryKey: ["dashboard-stats", 30],
    queryFn: () => systemApi.dashboardStats(30),
    retry: false,
  });
  const stats = statsQuery.data;

  const [intentText, setIntentText] = useState("");
  const [intentMode, setIntentMode] = useState<IntentTarget>("chat");

  // 继续学习：最近会话 + 进行中任务
  const conversationsQuery = useQuery({
    queryKey: ["conversations", "recent"],
    queryFn: () => conversationsApi.list(4),
    retry: false,
  });
  const recentConversations = conversationsQuery.data ?? [];

  const tasksQuery = useQuery({
    queryKey: ["tasks", "recent"],
    queryFn: () => tasksApi.list({ limit: 8 }),
    retry: false,
  });
  const activeTasks = (tasksQuery.data?.tasks ?? []).filter((t) =>
    ["running", "paused", "pending_review"].includes(t.status),
  );

  // 最近成果：试卷 + 学习资料档案
  const papersQuery = useQuery({
    queryKey: ["papers", "recent"],
    queryFn: () => papersApi.list(4),
    retry: false,
  });
  const recentPapers = papersQuery.data ?? [];

  const archivesQuery = useQuery({
    queryKey: ["study-archives", "recent"],
    queryFn: () => studyArchivesApi.list({ limit: 4 }),
    retry: false,
  });
  const recentArchives = archivesQuery.data?.items ?? [];

  const continueLoading = conversationsQuery.isLoading || tasksQuery.isLoading;
  const outcomesLoading = papersQuery.isLoading || archivesQuery.isLoading;

  const submitIntent = () => {
    const text = intentText.trim();
    if (!text) return;
    switch (intentMode) {
      case "chat":
        navigate("/chat", { state: { intentMessage: text } });
        break;
      case "compose":
        navigate("/compose", { state: { prefillKeyword: text } });
        break;
      case "materials":
        navigate("/materials", { state: { prefillQuery: text } });
        break;
      case "deepthink":
        navigate("/deepthink", { state: { prefillQuestion: text } });
        break;
    }
  };

  return (
    <div className="mx-auto max-w-4xl animate-fade-in space-y-8">
      {/* 欢迎区：大标题 + 轻量日期/本地状态 */}
      <section className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">
            {greetingForHour(now.getHours())}，{user?.username ?? "同学"}
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">{dateText}</p>
        </div>
        <div className="flex flex-col items-start gap-1.5 sm:items-end">
          <div className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs shadow-soft">
            {healthQuery.isLoading ? (
              <>
                <Skeleton className="size-2 rounded-full" />
                <Skeleton className="h-3 w-14" />
              </>
            ) : (
              <>
                <span className={cn("size-2 rounded-full", healthMeta.dot)} />
                <span className={healthMeta.text}>{healthMeta.label}</span>
              </>
            )}
          </div>
          {!healthQuery.isLoading && health && health.failed.length > 0 ? (
            <div className="text-xs text-muted-foreground">异常项：{health.failed.join("、")}</div>
          ) : null}
        </div>
      </section>

      {/* 第一主行动：今天想学习什么？ */}
      <section>
        <h2 className="mb-3 text-xl font-semibold tracking-tight">今天想学习什么？</h2>
        <PromptComposer
          value={intentText}
          onChange={setIntentText}
          onSubmit={submitIntent}
          placeholder={INTENT_PLACEHOLDERS[intentMode]}
          submitLabel="开始"
          autoFocus
          leftSlot={
            <div className="flex flex-wrap items-center gap-1">
              {INTENT_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  title={m.hint}
                  onClick={() => setIntentMode(m.id)}
                  className={cn(
                    "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
                    intentMode === m.id
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                  )}
                >
                  <m.icon className="size-3.5" />
                  {m.label}
                </button>
              ))}
            </div>
          }
        />
      </section>

      {/* 第二层：继续学习 */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">继续学习</h2>
          <Link to="/tasks" className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
            全部任务
            <ArrowRight className="size-3" />
          </Link>
        </div>
        {continueLoading ? (
          <div className="grid gap-2 sm:grid-cols-2">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-16 w-full rounded-xl" />
            ))}
          </div>
        ) : recentConversations.length === 0 && activeTasks.length === 0 ? (
          <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
            还没有进行中的学习内容，从上方输入开始
          </p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {recentConversations.map((c) => (
              <Link
                key={`conv-${c.id}`}
                to={`/chat/${c.id}`}
                className="group flex items-center gap-3 rounded-xl border border-border bg-card px-3.5 py-3 shadow-soft transition-shadow hover:shadow-lift"
              >
                <MessagesSquare className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{c.title || "未命名对话"}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    对话 · {c.updated_at ? formatRelative(c.updated_at) : ""}
                  </div>
                </div>
              </Link>
            ))}
            {activeTasks.slice(0, 4).map((t) => (
              <Link
                key={`task-${t.id}`}
                to="/tasks"
                className="group flex items-center gap-3 rounded-xl border border-border bg-card px-3.5 py-3 shadow-soft transition-shadow hover:shadow-lift"
              >
                <ListTodo className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-medium">
                      {t.title?.trim() || TASK_TYPE_LABELS[t.task_type] || "未命名任务"}
                    </div>
                    <Badge variant={t.status === "pending_review" ? "warning" : "muted"} className="shrink-0">
                      {TASK_STATUS_LABELS[t.status] ?? t.status}
                    </Badge>
                  </div>
                  <Progress value={clamp(t.progress ?? 0, 0, 100)} className="mt-1.5 h-1" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* 第三层：最近成果 */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">最近成果</h2>
          <div className="flex items-center gap-3">
            <Link to="/papers" className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
              试卷库
              <ArrowRight className="size-3" />
            </Link>
            <Link to="/materials" className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
              学习资料
              <ArrowRight className="size-3" />
            </Link>
          </div>
        </div>
        {outcomesLoading ? (
          <div className="grid gap-2 sm:grid-cols-2">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-16 w-full rounded-xl" />
            ))}
          </div>
        ) : recentPapers.length === 0 && recentArchives.length === 0 ? (
          <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
            还没有生成的试卷或资料
          </p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {recentPapers.map((p) => (
              <Link
                key={`paper-${p.paper_id}`}
                to={`/papers/${p.paper_id}`}
                className="group flex items-center gap-3 rounded-xl border border-border bg-card px-3.5 py-3 shadow-soft transition-shadow hover:shadow-lift"
              >
                <Files className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{p.paper_name}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    试卷 · {p.question_count} 题 · {formatRelative(p.created_at)}
                  </div>
                </div>
              </Link>
            ))}
            {recentArchives.map((a) => (
              <Link
                key={`archive-${a.id}`}
                to={`/materials/${a.id}`}
                className="group flex items-center gap-3 rounded-xl border border-border bg-card px-3.5 py-3 shadow-soft transition-shadow hover:shadow-lift"
              >
                <BookOpenText className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{a.topic || "未命名主题"}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    资料{a.subject ? ` · ${a.subject}` : ""}
                    {a.updated_at ? ` · ${formatRelative(a.updated_at)}` : ""}
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* 小型学习节奏（不再是首屏主体） */}
      <section className="rounded-xl border border-border bg-card px-4 py-3.5 shadow-soft">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">近 30 天</span>
          <span className="flex items-center gap-1.5">
            <ListTodo className="size-3.5" />
            {statsQuery.isLoading ? "…" : `${stats?.tasks_total ?? 0} 个任务`}
          </span>
          <span className="flex items-center gap-1.5">
            <CircleCheck className="size-3.5" />
            {statsQuery.isLoading ? "…" : `完成率 ${Math.round((stats?.completion_rate ?? 0) * 100)}%`}
          </span>
          <span className="flex items-center gap-1.5">
            <FileDown className="size-3.5" />
            {statsQuery.isLoading ? "…" : `导出 ${stats?.exports_total ?? 0} 份`}
          </span>
          <span className="flex items-center gap-1.5">
            <Timer className="size-3.5" />
            {statsQuery.isLoading ? "…" : `平均 ${formatDuration(stats?.avg_duration_s ?? 0)}`}
          </span>
          {stats?.top_subjects && stats.top_subjects.length > 0 ? (
            <span className="ml-auto truncate">
              常学：{stats.top_subjects.slice(0, 3).map((s) => s.subject).join("、")}
            </span>
          ) : null}
        </div>
      </section>
    </div>
  );
}
