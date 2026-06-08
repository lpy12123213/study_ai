import { useMemo, useState } from 'react'
import { useNotificationStore } from '@/stores/useNotificationStore'
import { EssayHistory, EssayInput, EssayResult, useEssayEvaluation } from '@/features/generation/essayEvaluation'

/**
 * Essay-evaluation page (中文/英文 作文批改).
 *
 * Three-pane layout:
 *
 *  - Left   – history list (recent evaluations).
 *  - Centre – essay composer (subject / type / language metadata + textarea).
 *  - Right  – scoring result with rubric breakdown + paragraph annotations.
 *
 * The page deliberately stays self-contained: the only cross-cutting concern
 * is the toast notification host, used to surface evaluation errors.
 */
export default function EssayEvaluationPage() {
  const pushToast = useNotificationStore((s) => s.pushToast)
  const { loading, error, result, evaluationId, essayText, evaluate, loadEvaluation } = useEssayEvaluation()
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const paragraphs = useMemo(() => {
    if (!result || !essayText.trim()) return undefined
    return essayText
      .split(/\n\s*\n/)
      .map((item) => item.trim())
      .filter(Boolean)
  }, [essayText, result])

  return (
    <div className="grid h-full grid-cols-1 gap-4 p-4 md:grid-cols-[260px_minmax(0,1fr)_minmax(0,1fr)]">
      <aside className="h-full overflow-hidden rounded-lg border border-border bg-card">
        <EssayHistory
          selectedId={selectedId ?? evaluationId}
          onSelect={async (record) => {
            setSelectedId(record.id)
            try {
              await loadEvaluation(record.id)
            } catch (caught) {
              const message = caught instanceof Error ? caught.message : 'evaluation_load_failed'
              pushToast({
                id: `essay-eval-load-error-${Date.now()}`,
                title: `加载批改记录失败：${message}`,
                status: 'failed',
              })
            }
          }}
        />
      </aside>

      <section className="h-full overflow-y-auto rounded-lg border border-border bg-card p-4">
        <h2 className="mb-3 text-lg font-semibold">作文批改</h2>
        <p className="mb-4 text-xs text-muted-foreground">
          AI 按维度对作文进行结构化评分，给出亮点 / 不足 / 修改建议与逐段批注。
        </p>
        <EssayInput
          loading={loading}
          onSubmit={async (payload) => {
            try {
              const response = await evaluate(payload)
              setSelectedId(response.evaluation_id)
            } catch (caught) {
              const message = caught instanceof Error ? caught.message : 'evaluation_failed'
              pushToast({
                id: `essay-eval-error-${Date.now()}`,
                title: `作文批改失败：${message}`,
                status: 'failed',
              })
            }
          }}
        />
        {error && (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
            {error}
          </div>
        )}
      </section>

      <section className="h-full overflow-y-auto rounded-lg border border-border bg-background p-4">
        {result ? (
          <EssayResult result={result} paragraphs={paragraphs} />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            提交作文后将在此查看评分与批注。
          </div>
        )}
      </section>
    </div>
  )
}
