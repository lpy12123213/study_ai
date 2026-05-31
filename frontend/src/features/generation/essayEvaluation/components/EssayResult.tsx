import type { EssayEvaluationResult } from '@/api/essayEvaluations'
import { cn } from '@/lib/utils'

export type EssayResultProps = {
  result: EssayEvaluationResult
  paragraphs?: string[]
}

/**
 * Score panel for a single evaluation result.
 *
 * Displays the rubric breakdown, total score, top strengths/weaknesses and the
 * paragraph-level annotations. The original essay paragraphs (if provided)
 * are rendered next to the LLM's per-paragraph feedback so teachers can see
 * the issue and the source text side by side.
 */
export function EssayResult({ result, paragraphs }: EssayResultProps) {
  const ratio = result.score_max > 0 ? result.score_total / result.score_max : 0

  return (
    <div className="space-y-6">
      <header className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="text-3xl font-bold text-primary">
            {result.score_total.toFixed(1)}
            <span className="ml-1 text-base font-normal text-muted-foreground">/ {result.score_max.toFixed(0)}</span>
          </span>
          {result.grade && (
            <span className="rounded-full bg-primary/10 px-3 py-1 text-sm font-medium text-primary">
              {result.grade}
            </span>
          )}
          <span className="text-xs text-muted-foreground">
            模型 {result.model || '—'} · {result.language === 'en' ? 'English' : '中文'}
          </span>
        </div>
        {result.summary && <p className="mt-2 text-sm leading-6 text-foreground">{result.summary}</p>}
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
          <div
            className={cn(
              'h-full rounded-full transition-all',
              ratio >= 0.85 ? 'bg-emerald-500' : ratio >= 0.7 ? 'bg-blue-500' : ratio >= 0.55 ? 'bg-amber-500' : 'bg-rose-500',
            )}
            style={{ width: `${Math.min(100, Math.round(ratio * 100))}%` }}
          />
        </div>
      </header>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="mb-2 text-sm font-semibold">评分维度</h3>
          <ul className="space-y-2">
            {result.scores.map((dim) => {
              const dimRatio = dim.max_score > 0 ? dim.score / dim.max_score : 0
              return (
                <li key={dim.name} className="space-y-1">
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="font-medium">{dim.name}</span>
                    <span className="text-muted-foreground">
                      {dim.score.toFixed(1)} / {dim.max_score.toFixed(0)}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn(
                        'h-full rounded-full',
                        dimRatio >= 0.8 ? 'bg-emerald-500' : dimRatio >= 0.6 ? 'bg-blue-500' : 'bg-amber-500',
                      )}
                      style={{ width: `${Math.min(100, Math.round(dimRatio * 100))}%` }}
                    />
                  </div>
                  {dim.comment && <p className="text-xs text-muted-foreground">{dim.comment}</p>}
                </li>
              )
            })}
          </ul>
        </div>

        <div className="space-y-3">
          {result.strengths.length > 0 && (
            <div className="rounded-lg border border-border bg-card p-4">
              <h3 className="mb-2 text-sm font-semibold text-emerald-700">亮点</h3>
              <ul className="list-disc space-y-1 pl-4 text-sm">
                {result.strengths.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {result.weaknesses.length > 0 && (
            <div className="rounded-lg border border-border bg-card p-4">
              <h3 className="mb-2 text-sm font-semibold text-rose-700">不足</h3>
              <ul className="list-disc space-y-1 pl-4 text-sm">
                {result.weaknesses.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {result.suggestions.length > 0 && (
            <div className="rounded-lg border border-border bg-card p-4">
              <h3 className="mb-2 text-sm font-semibold">修改建议</h3>
              <ul className="list-disc space-y-1 pl-4 text-sm">
                {result.suggestions.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      {result.paragraph_feedback.length > 0 && (
        <section className="rounded-lg border border-border bg-card p-4">
          <h3 className="mb-3 text-sm font-semibold">逐段批注</h3>
          <ul className="space-y-3">
            {result.paragraph_feedback.map((entry) => {
              const source = paragraphs?.[entry.index]
              return (
                <li key={entry.index} className="rounded-md border border-dashed border-border bg-muted/40 p-3">
                  <div className="mb-1 text-xs font-medium text-muted-foreground">第 {entry.index + 1} 段</div>
                  {source && <p className="mb-2 whitespace-pre-line text-sm text-foreground/80">{source}</p>}
                  {entry.issues.length > 0 && (
                    <ul className="list-disc space-y-0.5 pl-4 text-sm text-rose-700">
                      {entry.issues.map((issue) => (
                        <li key={issue}>{issue}</li>
                      ))}
                    </ul>
                  )}
                  {entry.suggestion && (
                    <p className="mt-2 text-sm text-emerald-700">建议：{entry.suggestion}</p>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {result.rewrite && (
        <section className="rounded-lg border border-border bg-card p-4">
          <h3 className="mb-2 text-sm font-semibold">改写示例</h3>
          <p className="whitespace-pre-line text-sm leading-6">{result.rewrite}</p>
        </section>
      )}
    </div>
  )
}
