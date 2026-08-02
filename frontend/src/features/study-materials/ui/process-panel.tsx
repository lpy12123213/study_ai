/**
 * 生成过程面板：顶部真实 TODO 清单 + 按 agentPath 分泳道的嵌套时间线。
 *
 * main 为主泳道，fill:* / fig:* 为可展开折叠的子泳道；思考块默认折叠。
 * 工具卡片复刻 chat 域 ToolStep 的视觉语言（本地实现，不跨 feature import）。
 */
import { useState } from "react";
import {
  Brain,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Image,
  ListChecks,
  ListTree,
  LoaderCircle,
  Minus,
  NotebookPen,
  PanelLeftClose,
  PenLine,
  Search,
  ShieldCheck,
  Square,
  Unplug,
  Wrench,
  X,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { ToolStepStatus, ToolStepView } from "@/features/chat/model/types";
import type { StudyMaterialTodo, StudyMaterialsTraceEntry } from "../model/types";
import { sectionStatusText } from "./section-status-text";

const TODO_TYPE_ICON: Record<string, typeof Circle> = {
  research: Search,
  backbone: ListTree,
  fill: PenLine,
  fig: Image,
  audit: ShieldCheck,
  revision: Wrench,
};

function todoStatusText(status: string): string {
  switch (status) {
    case "pending":
      return "待处理";
    case "in_progress":
      return "进行中";
    case "done":
      return "已完成";
    case "waived":
      return "已跳过";
    case "failed":
      return "失败";
    default:
      return status;
  }
}

function figureStatusText(status: string): string {
  switch (status) {
    case "success":
      return "成功";
    case "failed":
    case "error":
      return "失败";
    default:
      return status;
  }
}

/** 与 chat 域 TOOL_STATUS_META 相同的状态 → 图标/文案/颜色映射（本地副本，避免跨 feature import）。 */
function traceToolStatusMeta(status: ToolStepStatus): {
  label: string;
  className: string;
  Icon: typeof Circle;
} {
  switch (status) {
    case "running":
      return { label: "执行中", className: "text-tool-running", Icon: LoaderCircle };
    case "success":
      return { label: "已完成", className: "text-tool-success", Icon: CheckCircle2 };
    case "error":
      return { label: "失败", className: "text-tool-error", Icon: XCircle };
    case "interrupted":
      return { label: "已停止接收，状态未知", className: "text-tool-idle", Icon: Unplug };
    case "stopped":
      return { label: "已停止", className: "text-tool-idle", Icon: Square };
    default:
      return { label: "等待中", className: "text-tool-idle", Icon: Circle };
  }
}

function traceToolDurationMs(tool: ToolStepView): number | undefined {
  if (tool.serverDurationMs !== undefined) return tool.serverDurationMs;
  if (tool.observedStartAt === undefined || tool.observedResultAt === undefined) return undefined;
  return Math.max(0, tool.observedResultAt - tool.observedStartAt);
}

function formatTraceDuration(ms: number): string {
  const seconds = ms / 1000;
  return seconds < 10 ? `${seconds.toFixed(1)} 秒` : `${Math.round(seconds)} 秒`;
}

function laneTitle(agentPath: string): string {
  if (agentPath === "main") return "主流程";
  if (agentPath.startsWith("fill:")) return `填充 · ${agentPath.slice("fill:".length)}`;
  if (agentPath.startsWith("fig:")) return `配图 · ${agentPath.slice("fig:".length)}`;
  return agentPath;
}

/** 泳道排序：main 主泳道在前，其后 fill:* 与 fig:* 子泳道，未知泳道兜底最后。 */
function laneRank(agentPath: string): number {
  if (agentPath === "main") return 0;
  if (agentPath.startsWith("fill:")) return 1;
  if (agentPath.startsWith("fig:")) return 2;
  return 3;
}

function todoCleared(todo: StudyMaterialTodo): boolean {
  return todo.status === "done" || todo.status === "waived";
}

function TodoStatusIcon({ status }: { status: string }) {
  if (status === "done") return <Check aria-hidden className="size-3.5 shrink-0 text-tool-success" />;
  if (status === "in_progress") {
    return <LoaderCircle aria-hidden className="size-3.5 shrink-0 animate-spin text-tool-running" />;
  }
  if (status === "failed") return <X aria-hidden className="size-3.5 shrink-0 text-tool-error" />;
  if (status === "waived") return <Minus aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />;
  return <Circle aria-hidden className="size-3 shrink-0 text-tool-idle" />;
}

/** 顶部 TODO 清单：类型图标 + ref + 状态勾选（acceptance/note 放 title 提示）。 */
function TodoChecklist({ todos }: { todos: StudyMaterialTodo[] }) {
  return (
    <ul aria-label="生成 TODO 清单" className="space-y-1">
      {todos.map((todo) => {
        const TypeIcon = TODO_TYPE_ICON[todo.type] ?? Circle;
        const hint = [todo.acceptance, todo.note].filter(Boolean).join("；");
        return (
          <li
            key={todo.id}
            className="flex items-center gap-2 rounded-md px-2 py-1 text-xs"
            {...(hint ? { title: hint } : {})}
          >
            <TodoStatusIcon status={todo.status} />
            <TypeIcon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
            <span
              className={cn(
                "min-w-0 flex-1 truncate",
                todoCleared(todo) && "text-muted-foreground line-through",
              )}
            >
              {todo.ref || todo.id}
            </span>
            <span className="shrink-0 text-[11px] text-muted-foreground">
              {todoStatusText(todo.status)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** 思考块：相邻 thinking_delta 已由 reducer 合并，默认折叠。 */
function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-border bg-surface/50 px-3 py-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronRight className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
        <Brain aria-hidden className="size-3.5 shrink-0" />
        <span>思考过程 · {text.length} 字</span>
      </button>
      {open ? (
        <p className="mt-1.5 whitespace-pre-wrap pl-[22px] text-xs leading-5 text-muted-foreground">
          {text}
        </p>
      ) : null}
    </div>
  );
}

/** 工具调用卡：复刻 chat 域 ToolStep 的紧凑视觉（状态图标 + 名称 + 摘要 + 耗时）。 */
function TraceToolCard({ tool }: { tool: ToolStepView }) {
  const meta = traceToolStatusMeta(tool.status);
  const durationMs = traceToolDurationMs(tool);
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2" data-tool-status={tool.status}>
      <div className="flex items-center gap-2">
        <meta.Icon
          aria-hidden
          className={cn(
            "size-3.5 shrink-0",
            tool.status === "running" && "animate-spin",
            meta.className,
          )}
        />
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
          {tool.displayName}
        </span>
        <span className={cn("shrink-0 text-xs", meta.className)}>{meta.label}</span>
      </div>
      {tool.intent ? (
        <div className="mt-0.5 pl-[22px] text-xs text-muted-foreground">{tool.intent}</div>
      ) : null}
      {tool.summary ? (
        <div className="mt-0.5 pl-[22px] text-xs text-muted-foreground">
          {tool.summary}
          {durationMs !== undefined ? ` · ${formatTraceDuration(durationMs)}` : ""}
        </div>
      ) : null}
    </div>
  );
}

function TraceEntryView({ entry }: { entry: StudyMaterialsTraceEntry }) {
  switch (entry.kind) {
    case "thinking":
      return <ThinkingBlock text={entry.text} />;
    case "tool":
      return <TraceToolCard tool={entry.tool} />;
    case "note":
      return (
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
          <NotebookPen aria-hidden className="size-3.5 shrink-0 text-spectral" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
            笔记 · {entry.name}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground">{entry.chars} 字</span>
        </div>
      );
    case "figure":
      return (
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
          <Image aria-hidden className="size-3.5 shrink-0 text-spectral" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
            配图 {entry.figureId}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {entry.stage}
            {entry.status ? ` · ${figureStatusText(entry.status)}` : ""}
          </span>
        </div>
      );
    case "section":
      return (
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
          <PenLine aria-hidden className="size-3.5 shrink-0 text-spectral" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
            章节 {entry.secId}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {sectionStatusText(entry.status)}
          </span>
        </div>
      );
  }
}

function LaneEntries({ entries }: { entries: StudyMaterialsTraceEntry[] }) {
  return (
    <div className="space-y-1.5">
      {entries.map((entry) => (
        <TraceEntryView key={entry.id} entry={entry} />
      ))}
    </div>
  );
}

/** 子泳道（fill:* / fig:*）：可展开折叠；fill 泳道挂 section_fill 上报的章节状态徽标。 */
function SubLane({
  agentPath,
  entries,
  sectionStatus,
}: {
  agentPath: string;
  entries: StudyMaterialsTraceEntry[];
  sectionStatus: Record<string, string>;
}) {
  const [open, setOpen] = useState(true);
  const secId = agentPath.startsWith("fill:") ? agentPath.slice("fill:".length) : undefined;
  const secStatus = secId ? sectionStatus[secId] : undefined;
  const title = laneTitle(agentPath);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={open ? `收起 ${title} 泳道` : `展开 ${title} 泳道`}
        className="flex w-full items-center gap-1.5 py-1 text-left text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronRight className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {secStatus ? (
          <Badge variant={secStatus === "ok" ? "success" : "outline"}>
            {sectionStatusText(secStatus)}
          </Badge>
        ) : null}
        <span className="shrink-0 tabular-nums">{entries.length}</span>
      </button>
      {open ? (
        <div className="mt-1">
          <LaneEntries entries={entries} />
        </div>
      ) : null}
    </div>
  );
}

/** 过程面板：TODO 清单 + main 主泳道 + 嵌套子泳道时间线。 */
export function ProcessPanel({
  todos,
  traceByAgent,
  sectionStatus,
  onCollapse,
  className,
}: {
  todos: StudyMaterialTodo[];
  traceByAgent: Record<string, StudyMaterialsTraceEntry[]>;
  sectionStatus: Record<string, string>;
  /** 宽屏双栏下的折叠入口（窄屏 tabs 模式不传）。 */
  onCollapse?: () => void;
  className?: string;
}) {
  const lanes = Object.keys(traceByAgent)
    .filter((agentPath) => (traceByAgent[agentPath] ?? []).length > 0)
    .sort((a, b) => laneRank(a) - laneRank(b) || a.localeCompare(b));
  const subLanes = lanes.filter((agentPath) => agentPath !== "main");
  const mainEntries = lanes.includes("main") ? (traceByAgent.main ?? []) : [];
  const cleared = todos.filter(todoCleared).length;
  return (
    <section aria-label="生成过程" className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex shrink-0 items-center justify-between gap-2 px-4 py-3">
        <h3 className="text-xs font-semibold text-muted-foreground">生成过程</h3>
        <span className="flex items-center gap-1">
          {todos.length > 0 ? (
            <Badge variant="outline">
              TODO {cleared}/{todos.length}
            </Badge>
          ) : null}
          {onCollapse ? (
            <button
              type="button"
              onClick={onCollapse}
              aria-label="折叠过程面板"
              className="hidden size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-foreground lg:inline-flex"
            >
              <PanelLeftClose aria-hidden className="size-3.5" />
            </button>
          ) : null}
        </span>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 pb-4">
        {todos.length > 0 ? <TodoChecklist todos={todos} /> : null}
        {mainEntries.length > 0 ? (
          <div>
            <div className="py-1 text-xs font-medium text-muted-foreground">主流程</div>
            <LaneEntries entries={mainEntries} />
          </div>
        ) : null}
        {subLanes.length > 0 ? (
          <div className="space-y-2 border-l-2 border-timeline-rail pl-3">
            {subLanes.map((agentPath) => (
              <SubLane
                key={agentPath}
                agentPath={agentPath}
                entries={traceByAgent[agentPath] ?? []}
                sectionStatus={sectionStatus}
              />
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}

/** 步进器旁的紧凑真实 TODO 进度条；无 todos 数据时不渲染（保持现有推断步进器行为）。 */
export function StudyTodoProgress({ todos }: { todos: StudyMaterialTodo[] }) {
  if (todos.length === 0) return null;
  const cleared = todos.filter(todoCleared).length;
  const percent = Math.round((cleared / todos.length) * 100);
  const active = todos.find((todo) => todo.status === "in_progress");
  return (
    <div className="mt-2 flex items-center gap-2" aria-label="真实 TODO 进度">
      <ListChecks aria-hidden className="size-3 shrink-0 text-muted-foreground" />
      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
        TODO {cleared}/{todos.length}
      </span>
      <Progress value={percent} className="h-1 flex-1" aria-label="TODO 完成进度" />
      {active ? (
        <span className="min-w-0 truncate text-[11px] text-muted-foreground">
          进行中：{active.ref || active.id}
        </span>
      ) : null}
    </div>
  );
}
