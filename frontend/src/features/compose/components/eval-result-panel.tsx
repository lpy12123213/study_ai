import type { QuestionEvaluateResult } from "@/shared/api/types";
import { clamp } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { verdictVariant } from "../model/utils";


/** AI 鉴别结果展开区：verdict + 总分 + 维度条形 + 亮点/问题。 */
export function EvalResultPanel({ result }: { result: QuestionEvaluateResult }) {
  return (
    <div className="mt-2 space-y-3 rounded-lg border border-border bg-muted/40 p-3 animate-fade-in">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={verdictVariant(result.verdict)}>{result.verdict || "未评级"}</Badge>
        <span className="text-sm font-medium tabular-nums">{result.overall_score} 分</span>
        {result.summary ? <span className="text-xs text-muted-foreground">{result.summary}</span> : null}
      </div>
      {result.dimensions.length > 0 ? (
        <div className="space-y-1.5">
          {result.dimensions.map((d, i) => (
            <div key={`${d.name}-${i}`} className="flex items-center gap-2 text-xs" title={d.comment || undefined}>
              <span className="w-16 shrink-0 text-muted-foreground">{d.name}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${clamp(d.score, 0, 10) * 10}%` }}
                />
              </div>
              <span className="w-9 shrink-0 text-right tabular-nums text-muted-foreground">{d.score}/10</span>
            </div>
          ))}
        </div>
      ) : null}
      {result.highlights && result.highlights.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-success">亮点</div>
          <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
            {result.highlights.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {result.issues && result.issues.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-destructive">问题</div>
          <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
            {result.issues.map((it, i) => (
              <li key={i}>{it}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

