import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Copy, CopyPlus, FileDown, FileText, Share2 } from "lucide-react";

import { ApiError, downloadUrl } from "@/shared/api/http-client";
import { studyArchivesApi, studyMaterialsApi } from "@/features/study-materials/api";
import { shareApi } from "@/features/sharing/api";
import { STUDY_PRESETS, type StudyArchive } from "@/shared/api/types";
import { formatDateTime } from "@/lib/format";
import { useUiStore } from "@/stores/ui";
import { MarkdownView } from "@/components/markdown/markdown-view";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";

const PRESET_LABELS: Record<string, string> = Object.fromEntries(STUDY_PRESETS.map((p) => [p.value, p.label]));

function presetLabel(preset?: string): string {
  if (!preset) return "";
  return PRESET_LABELS[preset] ?? preset;
}

function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  return fallback;
}

function DetailSkeleton() {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6 md:px-8">
      <Skeleton className="h-8 w-24" />
      <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <Skeleton className="h-8 w-72 max-w-full" />
          <div className="flex gap-2">
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-5 w-16" />
            <Skeleton className="h-5 w-36" />
          </div>
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-8 w-20" />
          <Skeleton className="h-8 w-24" />
          <Skeleton className="h-8 w-20" />
        </div>
      </div>
      <Skeleton className="mt-6 h-[420px] w-full rounded-xl" />
    </div>
  );
}

function ArchiveNotFound() {
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-10 md:px-8">
      <EmptyState
        icon={FileText}
        title="档案不存在"
        description="该学习资料档案可能已被删除，或你没有访问权限。"
        action={
          <Button asChild variant="outline" size="sm">
            <Link to="/materials">
              <ArrowLeft />
              返回资料列表
            </Link>
          </Button>
        }
      />
    </div>
  );
}

function ArchiveDetailContent({ archive }: { archive: StudyArchive }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);

  const [cloneOpen, setCloneOpen] = useState(false);
  const [cloneTopic, setCloneTopic] = useState("");
  const [clonePreset, setClonePreset] = useState("standard");
  const [cloneRequirements, setCloneRequirements] = useState("");

  const [shareOpen, setShareOpen] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareExpiresAt, setShareExpiresAt] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const [latex, setLatex] = useState<{ tex_url: string; filename: string } | null>(null);

  const showUpdated = Boolean(archive.updated_at && archive.updated_at !== archive.created_at);
  const hasSections = Array.isArray(archive.sections) && archive.sections.length > 0;
  const hasAcceptance = Boolean(archive.acceptance && Object.keys(archive.acceptance).length > 0);

  const cloneMutation = useMutation({
    mutationFn: () =>
      studyArchivesApi.clone(archive.id, {
        topic: cloneTopic.trim(),
        preset: clonePreset,
        requirements: cloneRequirements.trim(),
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["study-archives"] });
      setCloneOpen(false);
      toast({ title: "克隆成功", description: "已基于当前档案创建副本", variant: "success" });
      navigate(`/materials/${res.archive.id}`);
    },
    onError: (err) => {
      toast({ title: "克隆失败", description: errorText(err, "网络异常，请稍后重试"), variant: "destructive" });
    },
  });

  const latexMutation = useMutation({
    mutationFn: () =>
      studyMaterialsApi.convertToLatex({
        markdown: archive.markdown ?? "",
        topic: archive.topic,
        subject: archive.subject,
      }),
    onSuccess: (res) => {
      if (res?.tex_url) {
        setLatex({ tex_url: res.tex_url, filename: res.filename || "material.tex" });
        toast({ title: "转换完成", description: "LaTeX 文件已生成，可点击下载", variant: "success" });
      } else {
        toast({ title: "转换失败", description: "后端未返回文件地址", variant: "destructive" });
      }
    },
    onError: (err) => {
      toast({ title: "转换失败", description: errorText(err, "网络异常，请稍后重试"), variant: "destructive" });
    },
  });

  const shareMutation = useMutation({
    mutationFn: () => shareApi.createLink({ item_type: "study_archive", item_id: String(archive.id) }),
    onSuccess: (res) => {
      setShareUrl(`${window.location.origin}/share/${res.token}`);
      setShareExpiresAt(res.expires_at ?? null);
    },
    onError: (err) => {
      toast({ title: "分享失败", description: errorText(err, "网络异常，请稍后重试"), variant: "destructive" });
    },
  });

  const openClone = () => {
    setCloneTopic(`${archive.topic ?? ""}（副本）`);
    setClonePreset(archive.preset || "standard");
    setCloneRequirements(archive.requirements ?? "");
    setCloneOpen(true);
  };

  const openShare = () => {
    setShareUrl(null);
    setShareExpiresAt(null);
    setCopied(false);
    setShareOpen(true);
    shareMutation.mutate();
  };

  const copyShareUrl = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      toast({ title: "已复制链接", variant: "success" });
    } catch {
      toast({ title: "复制失败", description: "请手动选中链接复制", variant: "warning" });
    }
  };

  const presetOptions: { value: string; label: string; desc: string }[] = STUDY_PRESETS.map((p) => ({
    value: p.value,
    label: p.label,
    desc: p.desc,
  }));
  if (clonePreset && !presetOptions.some((o) => o.value === clonePreset)) {
    presetOptions.push({ value: clonePreset, label: presetLabel(clonePreset), desc: "" });
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6 md:px-8 animate-fade-in">
      <Button variant="ghost" size="sm" className="-ml-2 text-muted-foreground" onClick={() => navigate(-1)}>
        <ArrowLeft />
        返回
      </Button>

      <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2.5">
          <h1 className="break-words text-2xl font-semibold tracking-tight">{archive.topic || "未命名档案"}</h1>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {archive.subject ? <Badge variant="secondary">{archive.subject}</Badge> : null}
            {archive.preset ? <Badge variant="outline">{presetLabel(archive.preset)}</Badge> : null}
            <span className="text-xs text-muted-foreground">创建于 {formatDateTime(archive.created_at)}</span>
            {showUpdated ? (
              <span className="text-xs text-muted-foreground">更新于 {formatDateTime(archive.updated_at)}</span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={openClone}>
            <CopyPlus />
            克隆
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => latexMutation.mutate()}
            disabled={latexMutation.isPending || !archive.markdown}
          >
            {latexMutation.isPending ? <Spinner /> : <FileText />}
            转 LaTeX
          </Button>
          <Button variant="outline" size="sm" onClick={openShare}>
            <Share2 />
            分享
          </Button>
        </div>
      </div>

      {archive.requirements ? (
        <blockquote className="mt-4 border-l-2 border-primary/40 pl-3 text-sm text-muted-foreground">
          {archive.requirements}
        </blockquote>
      ) : null}

      {latex ? (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-soft animate-fade-in">
          <div className="flex size-9 items-center justify-center rounded-md bg-success/10 text-success">
            <FileDown className="size-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium">LaTeX 文件已生成</div>
            <div className="truncate text-xs text-muted-foreground">{latex.filename}</div>
          </div>
          <Button size="sm" asChild>
            <a href={downloadUrl(latex.tex_url)} download={latex.filename}>
              <FileDown />
              下载 .tex
            </a>
          </Button>
        </div>
      ) : null}

      <Card className="mt-6">
        <CardContent className="pt-5">
          {archive.markdown ? (
            <MarkdownView content={archive.markdown} />
          ) : (
            <p className="text-sm text-muted-foreground">此档案暂无正文内容。</p>
          )}
        </CardContent>
      </Card>

      {hasSections || hasAcceptance ? (
        <Card className="mt-4">
          <CardContent className="pt-5">
            <Accordion type="multiple" className="[&>div:last-child]:border-b-0">
              {hasSections ? (
                <AccordionItem value="sections">
                  <AccordionTrigger>章节结构（{archive.sections?.length ?? 0}）</AccordionTrigger>
                  <AccordionContent>
                    <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
                      {JSON.stringify(archive.sections, null, 2)}
                    </pre>
                  </AccordionContent>
                </AccordionItem>
              ) : null}
              {hasAcceptance ? (
                <AccordionItem value="acceptance">
                  <AccordionTrigger>验收报告</AccordionTrigger>
                  <AccordionContent>
                    <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
                      {JSON.stringify(archive.acceptance, null, 2)}
                    </pre>
                  </AccordionContent>
                </AccordionItem>
              ) : null}
            </Accordion>
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={cloneOpen} onOpenChange={setCloneOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>克隆档案</DialogTitle>
            <DialogDescription>基于当前内容创建一份副本，可调整主题、档位与学习要求。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="clone-topic">主题</Label>
              <Input id="clone-topic" value={cloneTopic} onChange={(e) => setCloneTopic(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>生成档位</Label>
              <Select value={clonePreset} onValueChange={setClonePreset}>
                <SelectTrigger>
                  <SelectValue placeholder="选择档位" />
                </SelectTrigger>
                <SelectContent>
                  {presetOptions.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.desc ? `${o.label} · ${o.desc}` : o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="clone-requirements">学习要求</Label>
              <Textarea
                id="clone-requirements"
                rows={4}
                value={cloneRequirements}
                onChange={(e) => setCloneRequirements(e.target.value)}
                placeholder="可选，例如侧重例题讲解、加入思维导图等"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCloneOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() => cloneMutation.mutate()}
              disabled={!cloneTopic.trim() || cloneMutation.isPending}
            >
              {cloneMutation.isPending ? <Spinner className="text-primary-foreground" /> : null}
              确认克隆
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={shareOpen} onOpenChange={setShareOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>分享档案</DialogTitle>
            <DialogDescription>生成公开链接，获得链接的人可查看此档案内容。</DialogDescription>
          </DialogHeader>
          {shareMutation.isPending ? (
            <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
              <Spinner />
              正在生成分享链接…
            </div>
          ) : shareUrl ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Input readOnly value={shareUrl} onFocus={(e) => e.currentTarget.select()} />
                <Button variant="outline" size="icon" onClick={copyShareUrl} aria-label="复制链接">
                  {copied ? <Check className="text-success" /> : <Copy />}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                {shareExpiresAt ? `链接有效期至 ${formatDateTime(shareExpiresAt)}` : "链接长期有效"}
              </p>
            </div>
          ) : (
            <p className="py-2 text-sm text-destructive">链接生成失败，请关闭后重试。</p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function ArchiveDetailPage() {
  const { id } = useParams();
  const archiveId = Number(id);
  const validId = Number.isFinite(archiveId) && archiveId > 0;

  const query = useQuery({
    queryKey: ["study-archive", archiveId],
    queryFn: () => studyArchivesApi.get(archiveId),
    enabled: validId,
    retry: false,
  });

  if (!validId) return <ArchiveNotFound />;

  if (query.isPending) return <DetailSkeleton />;

  if (query.isError) {
    const err = query.error;
    if (err instanceof ApiError && err.status === 404) return <ArchiveNotFound />;
    return (
      <div className="mx-auto w-full max-w-4xl px-4 py-10 md:px-8">
        <EmptyState
          icon={FileText}
          title="加载失败"
          description={errorText(err, "网络异常，请稍后重试")}
          action={
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => query.refetch()}>
                重试
              </Button>
              <Button asChild variant="ghost" size="sm">
                <Link to="/materials">返回资料列表</Link>
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  return <ArchiveDetailContent key={query.data.id} archive={query.data} />;
}
