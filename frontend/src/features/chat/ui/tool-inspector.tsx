import { useState } from "react";
import { Link } from "react-router";
import { CheckCircle2, ExternalLink, FileImage, LibraryBig, ScrollText, XCircle } from "lucide-react";

import { downloadUrl } from "@/shared/api/http-client";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { StemHtml } from "@/components/question/stem-html";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { selectAllTools, selectToolStats } from "../model/selectors";
import {
  adaptToolDetail,
  adaptToolSources,
  formatToolArguments,
  type SourceItemView,
  type ToolDetailView,
} from "../model/tool-detail-adapters";
import type { ConversationTurnView, ToolStepView } from "../model/types";
import { formatObservedDuration } from "./format";
import { toolStatusLabel } from "./tool-status";
import { ToolStatusIcon } from "./tool-step";

// ---------- 小部件 ----------

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function KeyValueRows({ rows, emptyText }: { rows: { key: string; value: string }[]; emptyText: string }) {
  if (rows.length === 0) return <p className="text-xs text-muted-foreground">{emptyText}</p>;
  return (
    <dl className="space-y-1.5">
      {rows.map(({ key, value }) => (
        <div key={key} className="grid grid-cols-[minmax(96px,auto)_1fr] items-start gap-2 text-xs">
          <dt className="truncate font-mono text-muted-foreground" title={key}>
            {key}
          </dt>
          <dd className="whitespace-pre-wrap break-words font-mono leading-5 text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function RawJsonBlock({ title, value }: { title: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  if (value === undefined) return null;
  let text: string;
  try {
    text = JSON.stringify(value, null, 2) ?? "";
  } catch {
    text = String(value);
  }
  if (text.length > 4000) text = `${text.slice(0, 4000)}\n…（已截断）`;
  return (
    <div className="rounded-lg border border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        {title}
        <span className="text-[11px]">{open ? "收起" : "展开"}</span>
      </button>
      {open ? (
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all border-t border-border bg-muted/50 p-2.5 font-mono text-[11px] leading-5 text-muted-foreground">
          {text}
        </pre>
      ) : null}
    </div>
  );
}

const SOURCE_KIND_META: Record<SourceItemView["kind"], { label: string; Icon: typeof ExternalLink }> = {
  web: { label: "网络", Icon: ExternalLink },
  "question-bank": { label: "题库", Icon: LibraryBig },
  paper: { label: "试卷", Icon: ScrollText },
  file: { label: "文件", Icon: FileImage },
};

function SourceRow({ source }: { source: SourceItemView }) {
  const { label, Icon } = SOURCE_KIND_META[source.kind];
  const inner = (
    <>
      <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-xs font-medium text-foreground">{source.title}</span>
          <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">{label}</span>
        </div>
        {source.snippet ? <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{source.snippet}</div> : null}
      </div>
    </>
  );
  const className = "flex items-start gap-2 rounded-lg border border-border bg-surface px-2.5 py-2";
  if (!source.url) return <div className={className}>{inner}</div>;
  const external = /^https?:\/\//.test(source.url);
  return external ? (
    <a href={source.url} target="_blank" rel="noreferrer" className={cn(className, "transition-colors hover:bg-accent")}>
      {inner}
    </a>
  ) : (
    <Link to={source.url} className={cn(className, "transition-colors hover:bg-accent")}>
      {inner}
    </Link>
  );
}

// ---------- 领域结果视图 ----------

function ToolResultDetail({ tool }: { tool: ToolStepView }) {
  if (tool.status === "error") {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-tool-error/30 bg-tool-error/5 px-3 py-2.5 text-sm text-tool-error">
        <XCircle className="mt-0.5 size-4 shrink-0" />
        <div>
          <div className="font-medium">执行失败</div>
          <div className="mt-0.5 text-xs">{tool.summary ?? "未知错误"}</div>
        </div>
      </div>
    );
  }

  const detail: ToolDetailView = adaptToolDetail(tool.name, tool.result, tool.arguments);
  switch (detail.kind) {
    case "questions": {
      return (
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground">
            共找到 <span className="font-semibold text-foreground">{detail.count}</span> 道候选题
            {detail.keyword ? `，关键词「${detail.keyword}」` : ""}
          </div>
          {detail.appliedFilters.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {detail.appliedFilters.map((f) => (
                <span key={f.key} className="rounded-full bg-surface-mist px-2 py-0.5 text-[11px] text-muted-foreground">
                  {f.key}: {f.value}
                </span>
              ))}
            </div>
          ) : null}
          {detail.items.length === 0 ? (
            <p className="text-xs text-muted-foreground">结果中未包含题目明细。</p>
          ) : (
            <ul className="space-y-2">
              {detail.items.map((q) => (
                <li key={q.id} className="rounded-lg border border-border bg-surface p-2.5">
                  <div className="mb-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <span className="font-mono">{q.id}</span>
                    {q.difficulty ? <span className="rounded bg-muted px-1 py-0.5">{q.difficulty}</span> : null}
                    {q.knowledge.map((k) => (
                      <span key={k} className="rounded bg-surface-mist px-1 py-0.5">
                        {k}
                      </span>
                    ))}
                  </div>
                  {q.stem ? <StemHtml html={q.stem} className="max-h-40 overflow-y-auto text-xs" /> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    }

    case "compute": {
      return (
        <div className="space-y-3">
          {detail.purpose ? <div className="text-xs text-muted-foreground">目的：{detail.purpose}</div> : null}
          {detail.code ? (
            <pre className="overflow-x-auto rounded-lg border border-border bg-muted/50 p-2.5 font-mono text-xs leading-5">
              {detail.code}
            </pre>
          ) : null}
          {detail.resultRepr ? (
            <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
              <div className="text-xs text-muted-foreground">计算结果{detail.resultType ? `（${detail.resultType}）` : ""}</div>
              <div className="mt-1 whitespace-pre-wrap break-words font-mono text-sm font-semibold">{detail.resultRepr}</div>
            </div>
          ) : null}
          {detail.stdout ? (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-border bg-muted/50 p-2.5 font-mono text-[11px] leading-5 text-muted-foreground">
              {detail.stdout}
            </pre>
          ) : null}
          {detail.warnings.length > 0 ? (
            <ul className="space-y-1 text-xs text-warning">
              {detail.warnings.map((w, i) => (
                <li key={i}>⚠ {w}</li>
              ))}
            </ul>
          ) : null}
        </div>
      );
    }

    case "plot": {
      const src = downloadUrl(detail.url);
      return (
        <div className="space-y-2.5">
          {src ? (
            <a href={src} target="_blank" rel="noreferrer">
              <img src={src} alt={detail.filename ?? "函数图像"} className="w-full rounded-lg border border-border bg-white" />
            </a>
          ) : (
            <p className="text-xs text-muted-foreground">结果中未包含图像地址。</p>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {detail.filename ? <span className="font-mono">{detail.filename}</span> : null}
            {detail.bytes !== undefined ? <span>{formatBytes(detail.bytes)}</span> : null}
            {detail.cached ? <span className="rounded bg-muted px-1 py-0.5">缓存</span> : null}
            {src ? (
              <a href={src} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-spectral hover:underline">
                <ExternalLink className="size-3" /> 打开原图
              </a>
            ) : null}
          </div>
        </div>
      );
    }

    case "web": {
      return (
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground">
            {detail.query ? `查询「${detail.query}」` : "网络搜索"}
            {detail.provider ? ` · ${detail.provider}` : ""} · 返回 {detail.results.length} 个来源
          </div>
          {detail.answer ? <p className="rounded-lg bg-surface-mist px-3 py-2 text-xs leading-5">{detail.answer}</p> : null}
          <ul className="space-y-2">
            {detail.results.map((item, i) => (
              <li key={`${item.url ?? item.title}-${i}`} className="rounded-lg border border-border bg-surface px-2.5 py-2">
                <div className="flex items-center gap-1.5">
                  {item.url ? (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex min-w-0 items-center gap-1 text-xs font-medium text-spectral hover:underline"
                    >
                      <span className="truncate">{item.title}</span>
                      <ExternalLink className="size-3 shrink-0" />
                    </a>
                  ) : (
                    <span className="truncate text-xs font-medium">{item.title}</span>
                  )}
                  {item.publishedDate ? (
                    <span className="shrink-0 text-[11px] text-muted-foreground">{item.publishedDate}</span>
                  ) : null}
                </div>
                {item.snippet ? <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">{item.snippet}</p> : null}
              </li>
            ))}
          </ul>
        </div>
      );
    }

    case "paper": {
      return (
        <div className="space-y-2.5">
          <div className="flex items-center gap-2 rounded-lg border border-tool-success/30 bg-tool-success/5 px-3 py-2.5 text-sm">
            <CheckCircle2 className="size-4 text-tool-success" />
            <span>{detail.message ?? "试卷已创建"}</span>
          </div>
          {detail.paperId !== undefined ? (
            <Link
              to={`/papers/${detail.paperId}`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
            >
              打开试卷（ID: {detail.paperId}）
            </Link>
          ) : null}
        </div>
      );
    }

    case "papers": {
      return (
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">共 {detail.count} 份试卷</div>
          <ul className="space-y-1.5">
            {detail.papers.map((p) => (
              <li key={p.key} className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs">
                {p.value}
              </li>
            ))}
          </ul>
        </div>
      );
    }

    default:
      return <p className="text-xs text-muted-foreground">该工具暂无结构化的结果视图，可在「高级详情」查看原始返回。</p>;
  }
}

// ---------- 检查器 ----------

interface ToolInspectorProps {
  turn: ConversationTurnView;
  selectedToolId: string;
  onSelectTool: (id: string) => void;
}

/**
 * 右侧工具检查器（视觉规划 §7.7）。
 * 消费只读投影；不自动抢焦点，由「查看详情」显式打开。
 */
export function ToolInspector({ turn, selectedToolId, onSelectTool }: ToolInspectorProps) {
  const [tab, setTab] = useState("result");
  const tools = selectAllTools(turn);
  const stats = selectToolStats(turn);
  const tool = tools.find((t) => t.id === selectedToolId) ?? tools[tools.length - 1];

  if (!tool) {
    return <p className="p-4 text-xs text-muted-foreground">本轮还没有工具调用。</p>;
  }

  const argsRows = formatToolArguments(tool.arguments);
  const sources = adaptToolSources(tool.name, tool.result);
  const observedStart = tool.observedStartAt !== undefined ? new Date(tool.observedStartAt) : null;
  const observedEnd = tool.observedResultAt !== undefined ? new Date(tool.observedResultAt) : null;
  const timeFmt = (d: Date) =>
    `${d.toLocaleTimeString("zh-CN", { hour12: false })}.${String(d.getMilliseconds()).padStart(3, "0")}`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 头部：当前工具标识 */}
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <ToolStatusIcon status={tool.status} />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold">{tool.displayName}</span>
          <span className="shrink-0 rounded-full bg-surface-mist px-2 py-0.5 text-[11px] text-muted-foreground">
            第 {tool.iteration} 轮
          </span>
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          {toolStatusLabel(tool.status)}
          {tool.intent ? ` · ${tool.intent}` : ""}
        </div>
      </div>

      <Tabs
        value={tab}
        onValueChange={setTab}
        className="flex min-h-0 flex-1 flex-col px-3 pb-3 pt-2"
      >
        <TabsList className="grid w-full shrink-0 grid-cols-5">
          <TabsTrigger value="overview" className="px-1 text-xs">概览</TabsTrigger>
          <TabsTrigger value="args" className="px-1 text-xs">参数</TabsTrigger>
          <TabsTrigger value="result" className="px-1 text-xs">结果</TabsTrigger>
          <TabsTrigger value="sources" className="px-1 text-xs">来源</TabsTrigger>
          <TabsTrigger value="advanced" className="px-1 text-xs">详情</TabsTrigger>
        </TabsList>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <TabsContent value="overview" className="mt-3 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <StatCell label="工具数" value={String(stats.total)} />
              <StatCell label="当前轮次" value={stats.currentIteration !== undefined ? `第 ${stats.currentIteration} 轮` : "—"} />
              <StatCell label="成功" value={String(stats.success)} />
              <StatCell label="失败" value={String(stats.error)} />
            </div>
            {stats.observedSpanMs !== undefined ? (
              <div className="text-xs text-muted-foreground">
                观察耗时约 {formatObservedDuration(stats.observedSpanMs)}（客户端观察，非服务端权威耗时）
              </div>
            ) : null}
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-muted-foreground">本轮工具</div>
              {tools.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => {
                    onSelectTool(t.id);
                    setTab("result");
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-xs transition-colors",
                    t.id === tool.id ? "border-spectral/50 bg-accent" : "border-border bg-surface hover:bg-accent",
                  )}
                >
                  <ToolStatusIcon status={t.status} />
                  <span className="min-w-0 flex-1 truncate font-medium">{t.displayName}</span>
                  <span className="text-muted-foreground">第 {t.iteration} 轮</span>
                </button>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="args" className="mt-3">
            <KeyValueRows rows={argsRows} emptyText="该工具没有可展示的参数。" />
          </TabsContent>

          <TabsContent value="result" className="mt-3">
            <ToolResultDetail tool={tool} />
          </TabsContent>

          <TabsContent value="sources" className="mt-3">
            {sources.length === 0 ? (
              <p className="text-xs text-muted-foreground">该工具没有可验证的来源。</p>
            ) : (
              <ul className="space-y-2">
                {sources.map((s, i) => (
                  <li key={`${s.url ?? s.title}-${i}`}>
                    <SourceRow source={s} />
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>

          <TabsContent value="advanced" className="mt-3 space-y-2.5">
            <dl className="space-y-1 text-xs text-muted-foreground">
              <div className="flex justify-between gap-2">
                <dt>工具调用 ID</dt>
                <dd className="font-mono">{tool.id}</dd>
              </div>
              {observedStart ? (
                <div className="flex justify-between gap-2">
                  <dt>开始接收（客户端观察）</dt>
                  <dd className="font-mono">{timeFmt(observedStart)}</dd>
                </div>
              ) : null}
              {observedEnd ? (
                <div className="flex justify-between gap-2">
                  <dt>结果接收（客户端观察）</dt>
                  <dd className="font-mono">{timeFmt(observedEnd)}</dd>
                </div>
              ) : null}
            </dl>
            <RawJsonBlock title="原始参数（JSON）" value={tool.arguments} />
            <RawJsonBlock title="原始结果（JSON）" value={tool.result} />
            <p className="text-[11px] leading-5 text-muted-foreground">
              原始载荷默认折叠且超过 4000 字符截断；request ID 见网络请求日志（当前 Chat 流不在事件内携带）。
            </p>
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
