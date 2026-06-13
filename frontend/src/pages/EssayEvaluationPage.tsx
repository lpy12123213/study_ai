import { useMemo, useState } from 'react'
import { Sparkles } from 'lucide-react'
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
  const essayStats = [
    { label: '状态', value: loading ? '批改中' : result ? '已出报告' : '待提交' },
    { label: '文本长度', value: essayText.trim() ? `${essayText.trim().length} 字符` : '未输入' },
    { label: '段落', value: paragraphs ? `${paragraphs.length} 段` : '待分析' },
    { label: '当前记录', value: selectedId ?? evaluationId ? `#${selectedId ?? evaluationId}` : '新批改' },
  ]

  return (
    <div className="aurora-essay-screen flex h-full min-h-0 flex-col gap-4 p-4">
      <header className="aurora-essay-hero">
        <div>
          <div className="aurora-kicker">
            <Sparkles className="h-3.5 w-3.5" />
            Essay Evaluation Spectrum
          </div>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight">作文评价光谱舱</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            以维度评分、亮点诊断、问题定位和逐段批注组成完整反馈闭环，帮助学生把一次作文变成可执行的修改计划。
          </p>
        </div>
        <div className="aurora-essay-hero-grid">
          {essayStats.map((item) => (
            <div key={item.label} className="aurora-essay-stat">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 md:grid-cols-[270px_minmax(0,1fr)_minmax(0,1fr)]">
      <aside className="aurora-essay-panel h-full overflow-hidden rounded-lg">
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

      <section className="aurora-essay-panel h-full overflow-y-auto rounded-lg p-4">
        <div className="mb-4">
          <div className="aurora-kicker">Scoring input</div>
          <h2 className="mt-2 text-xl font-semibold">作文批改</h2>
        </div>
        <p className="mb-4 text-xs leading-5 text-muted-foreground">
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

      <section className="aurora-essay-panel h-full overflow-y-auto rounded-lg p-4">
        {result ? (
          <EssayResult result={result} paragraphs={paragraphs} />
        ) : (
          <div className="aurora-essay-empty flex h-full items-center justify-center text-sm text-muted-foreground">
            <div className="max-w-xs text-center">
              <div className="mx-auto mb-4 h-14 w-14 rounded-2xl border border-border/70 bg-background/70" />
              <div className="font-medium text-foreground">等待评分报告</div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">提交作文后将在此查看总分、维度拆解、亮点不足和逐段批注。</p>
            </div>
          </div>
        )}
      </section>
      </div>
    </div>
  )
}
