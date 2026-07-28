import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Copy,
  ExternalLink,
  FileDown,
  FileQuestion,
  Link2,
  Share2,
  Trash2,
} from "lucide-react";

import { ApiError, downloadUrl } from "@/shared/api/http-client";
import { papersApi } from "@/features/paper-library/api";
import { libraryApi } from "@/features/question-library/api";
import { shareApi } from "@/features/sharing/api";
import type { ExportResult, PaperQuestion } from "@/shared/api/types";
import { formatDateTime, normalizeProgress } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { QuestionCard } from "@/components/question/question-card";
import { MarkdownView } from "@/components/markdown/markdown-view";

type ToastFn = (t: { title: string; description?: string; variant?: "default" | "success" | "destructive" | "warning" }) => number;

const SOURCE_MODE_LABELS: Record<string, string> = {
  zujuan: "组卷网",
  local: "本地题库",
  hybrid: "混合来源",
};

const EXPORT_FORMATS = [
  { value: "markdown", label: "Markdown", desc: "纯文本，便于编辑与存档" },
  { value: "latex", label: "LaTeX", desc: "排版源码，适合二次加工" },
  { value: "pdf", label: "PDF", desc: "排版成品，可直接打印分发" },
  { value: "docx", label: "Word（DOCX）", desc: "便于在办公软件中修改" },
] as const;
type ExportFormat = (typeof EXPORT_FORMATS)[number]["value"];

const FORMAT_FILE_LABELS: Record<string, string> = {
  markdown: "Markdown 文件",
  latex: "LaTeX 文件",
  pdf: "PDF 文件",
  docx: "Word 文件",
};

interface ExportLink {
  key: string;
  label: string;
  url: string;
  filename?: string;
}

/** 从导出结果中收集全部可用下载链接（url / pdf_url / tex_url / 其他 *_url）。 */
function collectExportLinks(result: ExportResult): ExportLink[] {
  const links: ExportLink[] = [];
  const seen = new Set<string>();
  const push = (key: string, rawUrl: unknown, filename: unknown, label: string) => {
    if (typeof rawUrl !== "string" || !rawUrl.trim()) return;
    const url = downloadUrl(rawUrl);
    if (!url || seen.has(url)) return;
    seen.add(url);
    links.push({ key, label, url, filename: typeof filename === "string" ? filename : undefined });
  };
  push("url", result.url, result.filename, FORMAT_FILE_LABELS[result.format ?? ""] ?? "下载文件");
  push("pdf_url", result.pdf_url, result.pdf_filename, "PDF 文件");
  push("tex_url", result.tex_url, result.tex_filename, "TeX 文件");
  for (const [k, v] of Object.entries(result)) {
    if (!k.endsWith("_url") || k === "pdf_url" || k === "tex_url") continue;
    const base = k.slice(0, -"_url".length);
    push(k, v, result[`${base}_filename`], `${base.toUpperCase()} 文件`);
  }
  return links;
}

interface RadarItem {
  label: string;
  value: number;
  max: number;
}

/** radar_data 后端形状为 [{ subject, A, fullMark }]，这里做容错归一化。 */
function normalizeRadar(data?: Record<string, unknown>[]): RadarItem[] {
  if (!Array.isArray(data)) return [];
  const items = data.map((d) => ({
    label: String(d.subject ?? d.name ?? d.key ?? "未命名"),
    value: Number(d.A ?? d.value ?? 0) || 0,
    max: Number(d.fullMark ?? d.full_mark ?? d.max ?? 0) || 0,
  }));
  const fallbackMax = Math.max(1, ...items.map((i) => i.value));
  return items.map((i) => ({ ...i, max: i.max > 0 ? i.max : fallbackMax }));
}

async function copyText(text: string, toast: ToastFn, successTitle = "已复制") {
  try {
    await navigator.clipboard.writeText(text);
    toast({ title: successTitle, variant: "success" });
  } catch {
    toast({ title: "复制失败", description: "请手动选择文本复制", variant: "destructive" });
  }
}

function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.code === "paper_not_zujuan") return "仅组卷网来源的试卷支持生成下载链接";
    if (err.code === "rate_limited") return "请求过于频繁，请稍后再试";
    if (err.code === "pdf_compile_failed") return "PDF 编译失败，请确认本机 LaTeX 环境可用后重试";
    if (err.code === "split_export_failed") return "拆分导出失败，请尝试不拆分导出";
    if (err.code === "paper_export_failed") return "导出失败，请稍后重试或更换导出格式";
    return err.message || fallback;
  }
  return fallback;
}

/** 与后端 _infer_paper_source_mode 同一启发式：数字 id 为组卷网来源。 */
function inferSourceMode(questionIds: string[]): string {
  const ids = questionIds.map((x) => String(x ?? "").trim()).filter(Boolean);
  const hasDigits = ids.some((x) => /^\d+$/.test(x));
  const hasNonDigits = ids.some((x) => !/^\d+$/.test(x));
  if (hasDigits && hasNonDigits) return "hybrid";
  return hasDigits ? "zujuan" : "local";
}

/**
 * 题目列表。GET /api/papers/{id} 的响应模型不含题干（PaperResponse.QuestionInfo 无 stem 字段），
 * 这里对缺题干的题目逐条经题库详情接口补水（question_cache 命中才有题干/答案/解析）；
 * 未收录到本地题库的题目优雅降级为元信息 + 来源链接。
 */
function QuestionList({ questions }: { questions: PaperQuestion[] }) {
  const missingIds = questions.filter((q) => !q.stem && q.question_id).map((q) => q.question_id);

  const hydration = useQuery({
    queryKey: ["paper-question-hydration", missingIds],
    queryFn: async () => {
      const out: Record<string, { stem?: string; answer?: string; analysis?: string }> = {};
      await Promise.all(
        missingIds.map(async (qid) => {
          try {
            const res = await libraryApi.getItem(qid);
            const cache = (res?.question_cache ?? {}) as Record<string, any>;
            const item = (res?.library_item ?? {}) as Record<string, any>;
            const stem = String(cache.stem ?? item.stem ?? "").trim();
            out[qid] = {
              ...(stem ? { stem } : {}),
              ...(cache.answer ? { answer: String(cache.answer) } : {}),
              ...(cache.analysis ? { analysis: String(cache.analysis) } : {}),
            };
          } catch {
            // 未收录到本地题库——保持缺省，降级展示
            out[qid] = {};
          }
        }),
      );
      return out;
    },
    enabled: missingIds.length > 0,
    staleTime: 10 * 60_000,
    retry: false,
  });

  const map = hydration.data ?? {};
  const merged = questions.map((q) => {
    if (q.stem) return q;
    const h = map[q.question_id];
    return h ? { ...q, ...h } : q;
  });
  const dehydrated = merged.filter((q) => !q.stem).length;

  return (
    <div className="space-y-3">
      {hydration.isPending && missingIds.length > 0 ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Spinner /> 正在从本地题库加载题干…
        </div>
      ) : null}
      {dehydrated > 0 && !hydration.isPending ? (
        <p className="text-xs text-muted-foreground">
          {dehydrated} 道题目的题干未收录到本地题库，可通过「查看来源」访问原题页面。
        </p>
      ) : null}
      {merged.map((q, idx) => (
        <QuestionCard
          key={q.question_id || idx}
          question={q}
          actions={
            <>
              <Badge variant="muted">第 {q.order ?? idx + 1} 题</Badge>
              {q.source_url ? (
                <Button variant="ghost" size="sm" asChild className="h-7 px-2 text-xs text-muted-foreground">
                  <a href={q.source_url} target="_blank" rel="noreferrer">
                    <ExternalLink />
                    查看来源
                  </a>
                </Button>
              ) : null}
            </>
          }
        />
      ))}
    </div>
  );
}

function SwitchRow({
  id,
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
}: {
  id: string;
  label: string;
  description?: string;
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border px-3 py-2.5">
      <div className="min-w-0">
        <Label htmlFor={id}>{label}</Label>
        {description ? <p className="mt-0.5 text-xs text-muted-foreground">{description}</p> : null}
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} />
    </div>
  );
}

function ExportDialog({ paperId, paperName, onClose }: { paperId: number; paperName: string; onClose: () => void }) {
  const toast = useUiStore((s) => s.toast);
  const [format, setFormat] = useState<ExportFormat>("markdown");
  const [includeStem, setIncludeStem] = useState(true);
  const [includeAnswer, setIncludeAnswer] = useState(false);
  const [includeAnalysis, setIncludeAnalysis] = useState(false);
  const [splitBundle, setSplitBundle] = useState(false);
  const [result, setResult] = useState<ExportResult | null>(null);

  const showSplit = format === "latex" || format === "pdf";

  const mutation = useMutation({
    mutationFn: () =>
      papersApi.export(paperId, {
        format,
        includeStem,
        includeAnswer,
        includeAnalysis,
        splitBundle: showSplit && splitBundle,
      }),
    onSuccess: (data) => {
      setResult(data);
      toast({ title: "导出完成", description: "下载链接已生成", variant: "success" });
    },
    onError: (err) => {
      toast({ title: "导出失败", description: apiErrorMessage(err, "请稍后重试"), variant: "destructive" });
    },
  });

  const links = result ? collectExportLinks(result) : [];

  return (
    <Dialog open onOpenChange={(v) => (!v ? onClose() : undefined)}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>导出试卷</DialogTitle>
          <DialogDescription>将《{paperName}》导出为所选格式的文件</DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          <div className="space-y-2">
            <div className="text-sm font-medium">导出格式</div>
            <RadioGroup
              value={format}
              onValueChange={(v) => {
                const f = v as ExportFormat;
                setFormat(f);
                if (f !== "latex" && f !== "pdf") setSplitBundle(false);
              }}
              className="grid grid-cols-1 gap-2 sm:grid-cols-2"
            >
              {EXPORT_FORMATS.map((f) => (
                <Label
                  key={f.value}
                  htmlFor={`export-fmt-${f.value}`}
                  className={cn(
                    "flex cursor-pointer items-start gap-2.5 rounded-lg border border-border p-3 font-normal transition-colors hover:bg-accent/50",
                    format === f.value && "border-primary bg-primary/5 ring-1 ring-primary/30",
                  )}
                >
                  <RadioGroupItem id={`export-fmt-${f.value}`} value={f.value} className="mt-0.5" />
                  <span>
                    <span className="block text-sm font-medium">{f.label}</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">{f.desc}</span>
                  </span>
                </Label>
              ))}
            </RadioGroup>
          </div>

          <div className="space-y-2">
            <div className="text-sm font-medium">导出内容</div>
            <div className="space-y-2">
              <SwitchRow
                id="export-include-stem"
                label="包含题干"
                checked={includeStem}
                onCheckedChange={setIncludeStem}
                disabled={showSplit && splitBundle}
              />
              <SwitchRow
                id="export-include-answer"
                label="包含答案"
                checked={includeAnswer}
                onCheckedChange={setIncludeAnswer}
                disabled={showSplit && splitBundle}
              />
              <SwitchRow
                id="export-include-analysis"
                label="包含解析"
                checked={includeAnalysis}
                onCheckedChange={setIncludeAnalysis}
                disabled={showSplit && splitBundle}
              />
              {showSplit ? (
                <SwitchRow
                  id="export-split-bundle"
                  label="拆分试题/答案双文件"
                  description="试题与答案解析分别导出为两个文件"
                  checked={splitBundle}
                  onCheckedChange={setSplitBundle}
                />
              ) : null}
            </div>
          </div>

          {result ? (
            <div className="space-y-2 rounded-lg border border-border bg-muted/40 p-3 animate-fade-in">
              <div className="text-sm font-medium">下载链接</div>
              {links.length ? (
                <div className="space-y-1.5">
                  {links.map((l) => (
                    <div key={l.key} className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm">{l.label}</div>
                        {l.filename ? <div className="truncate text-xs text-muted-foreground">{l.filename}</div> : null}
                      </div>
                      <Button variant="outline" size="sm" asChild className="shrink-0">
                        <a href={l.url} target="_blank" rel="noreferrer">
                          <ExternalLink />
                          下载
                        </a>
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">导出成功，但未返回可用下载链接。</p>
              )}
              {result.expires_at ? (
                <p className="text-xs text-muted-foreground">
                  链接有效期至 {formatDateTime(result.expires_at)}，过期后请重新导出。
                </p>
              ) : null}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            关闭
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? <Spinner className="text-primary-foreground" /> : <FileDown />}
            {result ? "重新导出" : "开始导出"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DownloadLinksDialog({ paperId, onClose }: { paperId: number; onClose: () => void }) {
  const toast = useUiStore((s) => s.toast);
  const query = useQuery({
    queryKey: ["paper-download-link", paperId],
    queryFn: () => papersApi.downloadLink(paperId),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const data = query.data;

  return (
    <Dialog open onOpenChange={(v) => (!v ? onClose() : undefined)}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>组卷网下载链接</DialogTitle>
          <DialogDescription>
            {data?.question_count != null ? `共 ${data.question_count} 道题目的来源链接` : "按题目逐条访问组卷网下载"}
          </DialogDescription>
        </DialogHeader>

        {query.isPending ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Spinner /> 正在生成下载链接…
          </div>
        ) : query.isError ? (
          <Alert variant="destructive">
            <AlertDescription>{apiErrorMessage(query.error, "加载失败，请稍后重试")}</AlertDescription>
          </Alert>
        ) : data ? (
          <div className="space-y-4">
            {data.instructions?.length ? (
              <ol className="list-decimal space-y-1 rounded-lg bg-muted/60 p-3 pl-8 text-sm text-muted-foreground">
                {data.instructions.map((ins, i) => (
                  <li key={i}>{ins.replace(/^\s*\d+\s*[.、]?\s*/, "")}</li>
                ))}
              </ol>
            ) : null}
            {data.question_links?.length ? (
              <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
                {data.question_links.map((link, i) => (
                  <div key={`${link}-${i}`} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
                    <span className="w-7 shrink-0 text-xs text-muted-foreground">{i + 1}.</span>
                    <a
                      href={link}
                      target="_blank"
                      rel="noreferrer"
                      className="min-w-0 flex-1 truncate text-sm text-primary hover:underline"
                    >
                      {link}
                    </a>
                    <Button variant="ghost" size="icon-sm" aria-label="复制链接" onClick={() => copyText(link, toast)}>
                      <Copy />
                    </Button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">暂无可用链接。</p>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ShareDialog({
  paperName,
  data,
  isPending,
  error,
  onRetry,
  onClose,
}: {
  paperName: string;
  data?: { token: string; expires_at?: string | null; has_password?: boolean };
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
  onClose: () => void;
}) {
  const toast = useUiStore((s) => s.toast);
  const shareUrl = data?.token ? `${window.location.origin}/share/${data.token}` : "";

  return (
    <Dialog open onOpenChange={(v) => (!v ? onClose() : undefined)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>分享试卷</DialogTitle>
          <DialogDescription>生成公开链接，任何人可通过链接查看《{paperName}》</DialogDescription>
        </DialogHeader>

        {isPending ? (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Spinner /> 正在生成分享链接…
          </div>
        ) : error ? (
          <div className="space-y-3">
            <Alert variant="destructive">
              <AlertDescription>{apiErrorMessage(error, "生成分享链接失败，请稍后重试")}</AlertDescription>
            </Alert>
            <Button variant="outline" size="sm" onClick={onRetry}>
              重试
            </Button>
          </div>
        ) : data ? (
          <div className="space-y-3 animate-fade-in">
            <div className="flex items-center gap-2">
              <Input readOnly value={shareUrl} onFocus={(e) => e.target.select()} aria-label="分享链接" />
              <Button variant="outline" className="shrink-0" onClick={() => copyText(shareUrl, toast, "链接已复制")}>
                <Copy />
                复制
              </Button>
            </div>
            <div className="space-y-1 text-xs text-muted-foreground">
              <p>{data.expires_at ? `链接有效期至 ${formatDateTime(data.expires_at)}` : "链接长期有效"}</p>
              <p>{data.has_password ? "该链接已设置访问密码。" : "未设置访问密码（当前创建分享时暂不支持设置密码）。"}</p>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 animate-fade-in">
      <Skeleton className="h-8 w-28" />
      <Card>
        <CardHeader className="space-y-3">
          <Skeleton className="h-7 w-72" />
          <Skeleton className="h-4 w-48" />
        </CardHeader>
      </Card>
      <div className="space-y-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-32 w-full rounded-xl" />
        ))}
      </div>
    </div>
  );
}

export function PaperDetailPage() {
  const { id } = useParams();
  const paperId = Number(id);
  const validId = Number.isInteger(paperId) && paperId > 0;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);

  const [exportOpen, setExportOpen] = useState(false);
  const [linksOpen, setLinksOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const query = useQuery({
    queryKey: ["paper", paperId],
    queryFn: () => papersApi.get(paperId, true),
    enabled: validId,
    retry: false,
  });

  const deleteMutation = useMutation({
    mutationFn: () => papersApi.remove(paperId),
    onSuccess: () => {
      toast({ title: "试卷已删除", variant: "success" });
      void queryClient.invalidateQueries({ queryKey: ["papers"] });
      navigate("/papers");
    },
    onError: (err) => {
      toast({ title: "删除失败", description: apiErrorMessage(err, "请稍后重试"), variant: "destructive" });
    },
  });

  const shareMutation = useMutation({
    mutationFn: () => shareApi.createLink({ item_type: "paper", item_id: String(paperId) }),
  });

  const openShare = () => {
    setShareOpen(true);
    if (!shareMutation.data && !shareMutation.isPending) shareMutation.mutate();
  };

  if (!validId || query.isError) {
    const notFound =
      !validId || (query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 410));
    return (
      <div className="mx-auto w-full max-w-3xl animate-fade-in">
        <EmptyState
          icon={FileQuestion}
          title={notFound ? "试卷不存在" : "试卷加载失败"}
          description={
            notFound
              ? "该试卷可能已被删除，或链接地址有误。"
              : apiErrorMessage(query.error, "网络异常，请稍后重试")
          }
          action={
            <Button asChild>
              <Link to="/papers">
                <ArrowLeft />
                返回试卷列表
              </Link>
            </Button>
          }
        />
      </div>
    );
  }

  if (query.isPending || !query.data) return <PageSkeleton />;

  const paper = query.data;
  const analysis = paper.analysis;
  const difficultyPct = normalizeProgress(analysis?.difficulty_score);
  const radar = normalizeRadar(analysis?.radar_data);
  // PaperResponse 无 source_mode 字段——按后端同一启发式由题目 id 推导
  const sourceMode = paper.source_mode ?? inferSourceMode(paper.questions.map((q) => q.question_id));
  const sourceModeLabel = SOURCE_MODE_LABELS[sourceMode] ?? "未知来源";

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 animate-fade-in">
      <div>
        <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
          <Link to="/papers">
            <ArrowLeft />
            返回试卷列表
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 space-y-2">
              <CardTitle className="text-xl">{paper.paper_name}</CardTitle>
              <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <span>创建于 {formatDateTime(paper.created_at)}</span>
                <Badge variant="secondary">{sourceModeLabel}</Badge>
                <Badge variant="muted">{paper.questions.length} 题</Badge>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => setExportOpen(true)}>
                <FileDown />
                导出
              </Button>
              <Button variant="outline" size="sm" onClick={() => setLinksOpen(true)}>
                <Link2 />
                下载链接
              </Button>
              <Button variant="outline" size="sm" onClick={openShare}>
                <Share2 />
                分享
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => setDeleteOpen(true)}
              >
                <Trash2 />
                删除
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {analysis ? (
        <Card>
          <CardHeader>
            <CardTitle>试卷分析</CardTitle>
            <CardDescription>基于题目难度与题型分布自动生成</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {typeof analysis.difficulty_score === "number" ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">整体难度</span>
                  <span className="text-muted-foreground">{Math.round(difficultyPct)} / 100</span>
                </div>
                <Progress value={difficultyPct} />
              </div>
            ) : null}
            {radar.length ? (
              <div className="space-y-2.5">
                <div className="text-sm font-medium">题型 / 知识点分布</div>
                {radar.map((item) => (
                  <div key={item.label} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span>{item.label}</span>
                      <span className="text-muted-foreground">
                        {item.value} / {item.max} 题
                      </span>
                    </div>
                    <Progress value={(item.value / item.max) * 100} />
                  </div>
                ))}
              </div>
            ) : null}
            {analysis.ai_comment ? (
              <div className="space-y-2">
                <div className="text-sm font-medium">AI 评语</div>
                <MarkdownView content={analysis.ai_comment} className="text-sm" />
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">题目列表</h2>
          <span className="text-sm text-muted-foreground">共 {paper.questions.length} 题</span>
        </div>
        {paper.questions.length === 0 ? (
          <EmptyState icon={FileQuestion} title="试卷暂无题目" description="可通过组卷或题库向试卷中添加题目" />
        ) : (
          <QuestionList questions={paper.questions} />
        )}
      </section>

      {exportOpen ? <ExportDialog paperId={paperId} paperName={paper.paper_name} onClose={() => setExportOpen(false)} /> : null}
      {linksOpen ? <DownloadLinksDialog paperId={paperId} onClose={() => setLinksOpen(false)} /> : null}
      {shareOpen ? (
        <ShareDialog
          paperName={paper.paper_name}
          data={shareMutation.data}
          isPending={shareMutation.isPending}
          error={shareMutation.isError ? shareMutation.error : null}
          onRetry={() => shareMutation.mutate()}
          onClose={() => setShareOpen(false)}
        />
      ) : null}

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除试卷</DialogTitle>
            <DialogDescription>确定要删除《{paper.paper_name}》吗？此操作不可恢复。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
              {deleteMutation.isPending ? <Spinner className="text-destructive-foreground" /> : <Trash2 />}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
