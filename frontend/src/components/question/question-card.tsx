import { useState } from "react";
import { ChevronDown, ChevronUp, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { StemHtml } from "@/components/question/stem-html";
import { DifficultyBadge } from "@/components/question/difficulty-badge";
import { Spinner } from "@/components/ui/spinner";

export interface QuestionCardData {
  question_id?: string;
  stem?: string;
  answer?: string;
  analysis?: string;
  type?: string;
  question_type?: string;
  difficulty?: string;
  knowledge_point?: string;
  knowledge_points?: string[] | string;
  source?: string;
  source_url?: string;
  date?: string;
  quality_score?: number | null;
  ai_verdict?: string;
  has_answer?: boolean;
  has_analysis?: boolean;
}

function knowledgePoints(q: QuestionCardData): string[] {
  const kp = q.knowledge_points ?? q.knowledge_point;
  if (!kp) return [];
  if (Array.isArray(kp)) return kp.filter(Boolean).slice(0, 4);
  return String(kp)
    .split(/[,，、;；]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 4);
}

/** 题目卡片：题干（图片走代理）+ 元信息徽章 + 可选答案/解析折叠 + 右侧操作区。 */
export function QuestionCard({
  question,
  actions,
  selected,
  onSelect,
  defaultExpanded = false,
  expanded: controlledExpanded,
  onExpandedChange,
  detailLoading = false,
  detailError,
  onRetryDetail,
  className,
}: {
  question: QuestionCardData;
  actions?: React.ReactNode;
  selected?: boolean;
  onSelect?: (checked: boolean) => void;
  defaultExpanded?: boolean;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  detailLoading?: boolean;
  detailError?: string;
  onRetryDetail?: () => void;
  className?: string;
}) {
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
  const expanded = controlledExpanded ?? internalExpanded;
  const kps = knowledgePoints(question);
  const qtype = question.type ?? question.question_type;
  const hasDetail = Boolean(
    question.answer || question.analysis || question.has_answer || question.has_analysis || detailLoading || detailError,
  );
  const toggleExpanded = () => {
    const next = !expanded;
    if (controlledExpanded === undefined) setInternalExpanded(next);
    onExpandedChange?.(next);
  };
  const sourceHost = (() => {
    if (!question.source_url) return "";
    try {
      return new URL(question.source_url, window.location.origin).hostname || "查看来源";
    } catch {
      return "查看来源";
    }
  })();

  return (
    <Card
      className={cn(
        "group relative p-4 transition-shadow hover:shadow-lift",
        selected && "ring-2 ring-primary/50",
        className,
      )}
      style={{ contentVisibility: "auto", containIntrinsicSize: "240px" }}
    >
      <div className="flex items-start gap-3">
        {onSelect ? (
          <input
            type="checkbox"
            checked={selected ?? false}
            onChange={(e) => onSelect(e.target.checked)}
            className="mt-1 size-4 shrink-0 cursor-pointer accent-[var(--color-primary)]"
            aria-label="选择题目"
          />
        ) : null}
        <div className="min-w-0 flex-1">
          <div
            className={cn(hasDetail && "cursor-pointer")}
            onClick={(event) => {
              if (!hasDetail) return;
              const target = event.target as HTMLElement;
              if (target.closest("a, button, input")) return;
              toggleExpanded();
            }}
          >
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              {qtype ? <Badge variant="secondary">{qtype}</Badge> : null}
              <DifficultyBadge difficulty={question.difficulty} />
              {kps.map((kp) => (
                <Badge key={kp} variant="outline">
                  {kp}
                </Badge>
              ))}
              {question.quality_score != null ? (
                <Badge variant="muted">质量 {question.quality_score}</Badge>
              ) : null}
              {question.ai_verdict ? <Badge variant="default">{question.ai_verdict}</Badge> : null}
              {question.source ? <span className="text-xs text-muted-foreground">{question.source}</span> : null}
              {question.source_url ? (
                <a
                  href={question.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  {sourceHost}
                  <ExternalLink className="size-3" />
                </a>
              ) : null}
            </div>
            <StemHtml html={question.stem} className="text-[0.925rem]" />
          </div>
          {hasDetail ? (
            <div className="mt-2">
              <Button
                variant="ghost"
                size="sm"
                className="-ml-2 h-7 text-xs text-muted-foreground"
                onClick={toggleExpanded}
                aria-expanded={expanded}
              >
                {expanded ? <ChevronUp /> : <ChevronDown />}
                {expanded ? "收起答案解析" : "查看答案解析"}
              </Button>
              {expanded ? (
                <div className="mt-1 space-y-2 rounded-lg bg-muted/60 p-3 text-sm animate-fade-in">
                  {detailLoading ? (
                    <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
                      <Spinner />
                      正在加载答案与解析…
                    </div>
                  ) : detailError ? (
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-destructive">
                      <span>{detailError}</span>
                      {onRetryDetail ? (
                        <Button size="sm" variant="outline" onClick={onRetryDetail}>
                          重试
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                  {!detailLoading && !detailError && question.answer ? (
                    <div>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">答案</div>
                      <StemHtml html={question.answer} />
                    </div>
                  ) : null}
                  {!detailLoading && !detailError && question.analysis ? (
                    <div>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">解析</div>
                      <StemHtml html={question.analysis} />
                    </div>
                  ) : null}
                  {!detailLoading && !detailError && !question.answer && !question.analysis ? (
                    <div className="text-xs text-muted-foreground">当前来源未提供答案或解析。</div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-col items-end gap-1.5">{actions}</div> : null}
      </div>
    </Card>
  );
}
