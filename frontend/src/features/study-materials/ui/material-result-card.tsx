import { useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BookOpenCheck,
  ChevronDown,
  Copy,
  Download,
  ExternalLink,
  FileCode2,
  History,
} from "lucide-react";

import { MarkdownView } from "@/components/markdown/markdown-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Spinner } from "@/components/ui/spinner";
import { downloadUrl } from "@/shared/api/http-client";
import { formatDateTime } from "@/lib/format";
import {
  STUDY_PRESETS,
  type StudyArchive,
  type StudyMaterialResult,
} from "@/shared/api/types";
import { useUiStore } from "@/stores/ui";
import { cn } from "@/lib/utils";
import { studyArchivesApi } from "../api";

function presetLabelOf(value?: string): string {
  if (!value) return "";
  return STUDY_PRESETS.find((item) => item.value === value)?.label ?? value;
}

export function MaterialResultCard({
  result,
  markdown,
  preset,
  latexUrl,
  convertingLatex,
  onConvertLatex,
  compact,
}: {
  result: StudyMaterialResult;
  markdown: string;
  preset?: string;
  latexUrl?: string;
  convertingLatex?: boolean;
  onConvertLatex?: () => void;
  /** 「上一版成果」的折叠只读形态：不渲染正文与 LaTeX 转换入口。 */
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const toast = useUiStore((state) => state.toast);
  const material = result.material ?? {};
  const mdUrl = material.md_url ?? result.md_url;
  const pdfUrl = material.pdf_url ?? result.pdf_url;
  const texUrl = latexUrl ?? material.tex_url ?? result.tex_url;
  const sections = Array.isArray(material.sections) ? material.sections.length : undefined;
  const presetLabel = presetLabelOf(preset);
  const degraded = result.degraded === true || material.passed === false;
  const issues = Array.isArray(material.issues)
    ? material.issues.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];

  // 档案链接解析：优先按主题精确匹配最近档案；失败时退回档案列表页。
  const topic = typeof material.topic === "string" && material.topic.trim() ? material.topic.trim() : undefined;
  const archiveQuery = useQuery({
    queryKey: ["study-archives", "resolve", topic],
    queryFn: async () => {
      const res = await studyArchivesApi.list({ limit: 50 });
      return res.items.find((item) => item.topic === topic) ?? null;
    },
    enabled: Boolean(topic),
    staleTime: 60_000,
    retry: false,
  });
  const archive = archiveQuery.data ?? null;
  const baseFingerprint = archive?.base_fingerprint?.trim() || undefined;

  const [historyOpen, setHistoryOpen] = useState(false);
  const [versionPreview, setVersionPreview] = useState<StudyArchive | null>(null);
  const [versionLoading, setVersionLoading] = useState(false);
  const historyQuery = useQuery({
    queryKey: ["study-archives", "history", baseFingerprint],
    queryFn: () => studyArchivesApi.listByBaseFingerprint(baseFingerprint as string, { limit: 20 }),
    enabled: historyOpen && Boolean(baseFingerprint),
    staleTime: 30_000,
    retry: false,
  });
  const versions = historyQuery.data?.items ?? [];

  const copyMarkdown = async () => {
    if (!markdown) return;
    try {
      await navigator.clipboard.writeText(markdown);
      toast({ title: "已复制 Markdown", variant: "success" });
      return;
    } catch {
      // 剪贴板 API 被禁用（非安全上下文等）时走 execCommand 兜底。
    }
    const textarea = document.createElement("textarea");
    textarea.value = markdown;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      toast({ title: "已复制 Markdown", variant: "success" });
    } catch {
      toast({ title: "复制失败", description: "浏览器未允许访问剪贴板", variant: "destructive" });
    } finally {
      textarea.remove();
    }
  };

  const openVersion = async (id: number) => {
    setVersionLoading(true);
    try {
      const detail = await studyArchivesApi.get(id);
      setVersionPreview(detail);
    } catch {
      toast({ title: "历史版本加载失败", description: "请稍后重试", variant: "destructive" });
    } finally {
      setVersionLoading(false);
    }
  };

  const downloadButtons = (
    <>
      {mdUrl ? (
        <Button size="sm" asChild>
          <a href={downloadUrl(mdUrl)} target="_blank" rel="noreferrer">
            <Download /> 下载 Markdown
          </a>
        </Button>
      ) : null}
      {pdfUrl ? (
        <Button variant="outline" size="sm" asChild>
          <a href={downloadUrl(pdfUrl)} target="_blank" rel="noreferrer">
            <Download /> 下载 PDF
          </a>
        </Button>
      ) : null}
      {texUrl ? (
        <Button variant="outline" size="sm" asChild>
          <a href={downloadUrl(texUrl)} target="_blank" rel="noreferrer">
            <ExternalLink /> 下载 LaTeX
          </a>
        </Button>
      ) : null}
      {markdown ? (
        <Button variant="outline" size="sm" onClick={() => void copyMarkdown()}>
          <Copy /> 复制 Markdown
        </Button>
      ) : null}
    </>
  );

  const historyPopover = baseFingerprint ? (
    <>
      <Popover open={historyOpen} onOpenChange={setHistoryOpen}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="sm">
            <History /> 历史版本
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-72">
          <div className="text-sm font-semibold">版本历史</div>
          {historyQuery.isPending ? (
            <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <Spinner /> 加载版本…
            </div>
          ) : versions.length === 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">仅当前版本</p>
          ) : (
            <ul className="mt-2 space-y-1">
              {versions.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => void openVersion(item.id)}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent"
                  >
                    <span className="text-muted-foreground">{formatDateTime(item.created_at)}</span>
                    {item.preset ? <Badge variant="outline">{presetLabelOf(item.preset)}</Badge> : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </PopoverContent>
      </Popover>
      <Dialog
        open={versionLoading || versionPreview !== null}
        onOpenChange={(open) => {
          if (!open) setVersionPreview(null);
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{versionPreview?.topic || "历史版本"}</DialogTitle>
            <DialogDescription>
              {versionPreview
                ? `${formatDateTime(versionPreview.created_at)}${
                    versionPreview.preset ? ` · ${presetLabelOf(versionPreview.preset)}` : ""
                  }`
                : "正在加载选中的历史版本"}
            </DialogDescription>
          </DialogHeader>
          {versionLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Spinner /> 正在加载版本内容…
            </div>
          ) : (
            <div className="max-h-[70vh] overflow-y-auto pr-1">
              <MarkdownView content={versionPreview?.markdown} />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  ) : null;

  if (compact) {
    return (
      <article
        aria-label="上一版成果"
        className="rounded-xl border border-border bg-card px-4 py-3 shadow-soft"
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="flex min-w-0 flex-1 items-center gap-2">
            <BookOpenCheck className="size-4 shrink-0 text-tool-success" />
            <span className="shrink-0 text-xs text-muted-foreground">上一版成果</span>
            <span className="min-w-0 truncate text-sm font-medium">
              {material.topic || "学习资料讲义"}
            </span>
            {presetLabel ? <Badge>{presetLabel}</Badge> : null}
          </span>
          <span className="flex flex-wrap gap-2">{downloadButtons}</span>
        </div>
      </article>
    );
  }

  return (
    <article className="overflow-hidden rounded-2xl border border-border bg-card shadow-lift">
      <div className="border-b border-border bg-gradient-to-br from-spectral/5 via-card to-spectral-edge/5 px-5 py-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs font-semibold text-spectral">讲义已完成</div>
            <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
              {material.topic || "学习资料讲义"}
            </h2>
          </div>
          {historyPopover}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {presetLabel ? <Badge>{presetLabel}</Badge> : null}
          {material.subject ? <Badge variant="muted">{material.subject}</Badge> : null}
          {sections !== undefined ? <Badge variant="outline">{sections} 个知识点</Badge> : null}
          {typeof material.passed === "boolean" ? (
            <Badge variant={material.passed ? "success" : "warning"}>
              {material.passed ? "审查通过" : "仍有质量提示"}
            </Badge>
          ) : null}
        </div>
      </div>

      {degraded ? (
        <div className="border-b border-warning/40 bg-warning/10 px-5 py-3" role="alert">
          <div className="flex items-center gap-2 text-sm font-medium text-warning-foreground dark:text-warning">
            <AlertTriangle className="size-4 shrink-0" />
            本次成果未完全通过质量审查
          </div>
          {issues.length > 0 ? (
            <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-xs leading-5 text-muted-foreground">
              {issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <div className="px-5 py-5">
        {markdown ? (
          <>
            <div className={cn("relative overflow-hidden", !expanded && "max-h-[31rem]")}>
              <MarkdownView content={markdown} />
              {!expanded ? (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-card to-transparent" />
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-spectral hover:underline"
            >
              {expanded ? "收起全文" : "展开阅读全文"}
              <ChevronDown className={cn("size-3.5 transition-transform", expanded && "rotate-180")} />
            </button>
          </>
        ) : (
          <p className="text-sm leading-6 text-muted-foreground">
            该任务已完成并保存到资料档案。当前完成事件未携带 Markdown 正文，可在资料档案中打开成果或下载生成文件。
          </p>
        )}
      </div>

      <div className="flex flex-col gap-3 border-t border-border bg-chrome-surface px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <BookOpenCheck className="size-4 text-tool-success" />
          <Link
            to={archive ? `/materials/${archive.id}` : "/materials"}
            className="transition-colors hover:text-foreground hover:underline"
          >
            已自动保存到资料档案
          </Link>
          {material.expires_at ? ` · 下载链接有效期至 ${formatDateTime(material.expires_at)}` : ""}
        </div>
        <div className="flex flex-wrap gap-2">
          {downloadButtons}
          {!texUrl && markdown && onConvertLatex ? (
            <Button variant="outline" size="sm" onClick={onConvertLatex} disabled={convertingLatex}>
              <FileCode2 />
              {convertingLatex ? "转换中…" : "转 LaTeX"}
            </Button>
          ) : null}
        </div>
      </div>
    </article>
  );
}
