import { Link } from "react-router";
import { BookOpenText, Clock3, FileText, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  STUDY_PRESETS,
  TASK_STATUS_LABELS,
  type StudyArchiveSummary,
  type StudyPreset,
  type TaskSummary,
} from "@/shared/api/types";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

const EXAMPLES = ["函数单调性", "受力分析入门", "英语虚拟语气", "光合作用与呼吸作用"];

export function MaterialsWelcome({
  preset,
  onPresetChange,
  onExample,
  archives,
  archivesPending,
  recentTasks,
}: {
  preset: StudyPreset;
  onPresetChange: (preset: StudyPreset) => void;
  onExample: (query: string) => void;
  archives: StudyArchiveSummary[];
  archivesPending: boolean;
  recentTasks: TaskSummary[];
}) {
  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col justify-center py-8 lg:py-12">
      <div className="mb-8">
        <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.22em] text-spectral">
          <span className="h-px w-6 bg-spectral" />
          Study materials
        </div>
        <h1 className="max-w-3xl font-display text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
          说出想学的主题，
          <br className="hidden sm:block" />
          为你写成一份
          <span className="bg-gradient-to-r from-spectral to-spectral-edge bg-clip-text text-transparent">
            可以下载的讲义
          </span>
          。
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
          我会先拆解知识点，再逐点检索权威资料、匹配题库例题，最后写成带讲解与练习的 Markdown 讲义，并自动保存到资料档案。
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {STUDY_PRESETS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => onPresetChange(item.value)}
            className={cn(
              "rounded-xl border bg-card p-3.5 text-left shadow-soft transition-colors hover:border-spectral/40",
              preset === item.value
                ? "border-spectral ring-2 ring-spectral/15"
                : "border-border",
            )}
          >
            <span className="flex items-center justify-between text-sm font-semibold">
              {item.label}
              {preset === item.value ? <span className="text-spectral">✓</span> : null}
            </span>
            <span className="mt-1 block text-xs leading-5 text-muted-foreground">{item.desc}</span>
          </button>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">试试</span>
        {EXAMPLES.map((example, index) => (
          <button
            key={example}
            type="button"
            onClick={() => onExample(example)}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs shadow-soft transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            {index === 0 ? <Sparkles className="size-3 text-spectral" /> : null}
            {example}
          </button>
        ))}
      </div>

      {(archivesPending || archives.length > 0) ? (
        <section className="mt-8" aria-labelledby="recent-archives-title">
          <div className="mb-2.5 flex items-center justify-between">
            <h2 id="recent-archives-title" className="text-sm font-semibold">
              最近成果
            </h2>
            <span className="text-xs text-muted-foreground">最近 {Math.min(archives.length, 2)} 项</span>
          </div>
          {archivesPending ? (
            <div className="space-y-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : (
            <div className="space-y-2">
              {archives.slice(0, 2).map((archive) => (
                <Link
                  key={archive.id}
                  to={`/materials/${archive.id}`}
                  className="flex items-center gap-3 rounded-xl border border-border bg-card px-3.5 py-3 shadow-soft transition-colors hover:bg-accent"
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-spectral/10 text-spectral">
                    <FileText className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{archive.topic || "未命名讲义"}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-1.5">
                      {archive.subject ? <Badge variant="muted">{archive.subject}</Badge> : null}
                      {archive.preset ? (
                        <Badge variant="default">
                          {STUDY_PRESETS.find((item) => item.value === archive.preset)?.label ?? archive.preset}
                        </Badge>
                      ) : null}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">{formatRelative(archive.updated_at ?? archive.created_at)}</span>
                </Link>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {recentTasks.length > 0 ? (
        <section className="mt-5" aria-labelledby="recent-material-tasks-title">
          <h2 id="recent-material-tasks-title" className="mb-2 text-xs font-semibold text-muted-foreground">
            最近生成
          </h2>
          <div className="flex flex-wrap gap-2">
            {recentTasks.slice(0, 4).map((task) => (
              <Tooltip key={task.id}>
                <TooltipTrigger asChild>
                  <Link
                    to={`/materials?task=${encodeURIComponent(task.id)}`}
                    className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                  >
                    {task.status === "running" ? (
                      <Clock3 className="size-3 text-tool-running" />
                    ) : (
                      <BookOpenText className="size-3 text-tool-success" />
                    )}
                    <span className="max-w-48 truncate">{task.title || "学习资料"}</span>
                  </Link>
                </TooltipTrigger>
                <TooltipContent>
                  状态：{TASK_STATUS_LABELS[task.status] ?? task.status} · 点击恢复视图
                </TooltipContent>
              </Tooltip>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
