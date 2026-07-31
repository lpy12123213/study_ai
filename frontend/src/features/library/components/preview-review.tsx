import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { libraryApi } from "@/features/question-library/api";
import type { DraftQuestion, LibraryPreview } from "@/shared/api/types";
import { useUiStore } from "@/stores/ui";
import { cn } from "@/lib/utils";
import { clamp } from "@/lib/format";
import { generatedFileUrl, proxyImageUrl } from "@/lib/media";
import { StemHtml } from "@/components/question/stem-html";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { SectionKey } from "../model/shared";
import { apiErrorText } from "../model/shared";
import { verdictVariant } from "../model/shared";


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

export function PreviewReview({ preview, onExit }: { preview: LibraryPreview; onExit: (committed: boolean) => void }) {
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

