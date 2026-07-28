import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { StemHtml } from "@/components/question/stem-html";
import { DifficultyBadge } from "@/components/question/difficulty-badge";

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
  className,
}: {
  question: QuestionCardData;
  actions?: React.ReactNode;
  selected?: boolean;
  onSelect?: (checked: boolean) => void;
  defaultExpanded?: boolean;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const kps = knowledgePoints(question);
  const qtype = question.type ?? question.question_type;
  const hasDetail = Boolean(question.answer || question.analysis);

  return (
    <Card
      className={cn(
        "group relative p-4 transition-shadow hover:shadow-lift",
        selected && "ring-2 ring-primary/50",
        className,
      )}
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
          </div>
          <StemHtml html={question.stem} className="text-[0.925rem]" />
          {hasDetail ? (
            <div className="mt-2">
              <Button
                variant="ghost"
                size="sm"
                className="-ml-2 h-7 text-xs text-muted-foreground"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? <ChevronUp /> : <ChevronDown />}
                {expanded ? "收起答案解析" : "查看答案解析"}
              </Button>
              {expanded ? (
                <div className="mt-1 space-y-2 rounded-lg bg-muted/60 p-3 text-sm animate-fade-in">
                  {question.answer ? (
                    <div>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">答案</div>
                      <StemHtml html={question.answer} />
                    </div>
                  ) : null}
                  {question.analysis ? (
                    <div>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">解析</div>
                      <StemHtml html={question.analysis} />
                    </div>
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
