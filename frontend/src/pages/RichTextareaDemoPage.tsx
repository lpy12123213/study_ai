import { useMemo, useState } from 'react'
import { RichTextarea } from '@/components/shared/RichTextarea'
import { Markdown } from '@/components/shared/Markdown'

const INITIAL_VALUE = [
  '设 \\(f(x)=x^2+1\\)，求导并说明单调性。',
  '',
  '$$',
  "f'(x)=2x",
  '$$',
].join('\n')

export default function RichTextareaDemoPage() {
  const [value, setValue] = useState(INITIAL_VALUE)
  const [submitCount, setSubmitCount] = useState(0)
  const wordCount = useMemo(() => value.trim().length, [value])

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-4 p-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">RichTextarea</h1>
          <div className="text-xs text-muted-foreground tabular-nums">
            {wordCount} chars · submits {submitCount}
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="min-h-0 rounded-lg border bg-card p-3">
          <RichTextarea
            value={value}
            onChange={setValue}
            onSubmit={() => setSubmitCount((count) => count + 1)}
            placeholder="输入含公式的 Markdown"
            minHeight={320}
            maxHeight={560}
            submitOnEnter
          />
        </section>

        <section className="min-h-0 overflow-auto rounded-lg border bg-background p-4">
          <Markdown content={value} />
        </section>
      </div>

      <pre className="max-h-44 overflow-auto rounded-lg border bg-muted/30 p-3 text-xs leading-5">
        {value}
      </pre>
    </div>
  )
}
