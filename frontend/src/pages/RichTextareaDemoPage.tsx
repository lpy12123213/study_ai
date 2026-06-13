import { useMemo, useState } from 'react'
import { Code2, Eye, Sparkles, Type } from 'lucide-react'
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
    <div className="aurora-rich-demo-screen flex h-full flex-col gap-4 overflow-hidden p-4">
      <div className="aurora-rich-demo-hero flex items-end justify-between gap-3 p-5">
        <div>
          <div className="aurora-rich-demo-kicker">
            <Sparkles className="h-4 w-4" />
            <span>Markdown Formula Lab</span>
          </div>
          <h1>RichTextarea</h1>
          <p>测试公式、Markdown、Enter 提交与预览渲染的输入实验台。</p>
        </div>
        <div className="aurora-rich-demo-stats">
          <div>
            <span>Chars</span>
            <strong>{wordCount}</strong>
          </div>
          <div>
            <span>Submits</span>
            <strong>{submitCount}</strong>
          </div>
        </div>
      </div>

      <div className="mx-auto grid min-h-0 w-full max-w-6xl flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="aurora-rich-demo-panel min-h-0 p-3">
          <div className="aurora-rich-demo-panel-title">
            <Type className="h-4 w-4" />
            <span>编辑输入</span>
          </div>
          <div className="aurora-rich-demo-editor">
            <RichTextarea
              value={value}
              onChange={setValue}
              onSubmit={() => setSubmitCount((count) => count + 1)}
              placeholder="输入含公式的 Markdown"
              minHeight={320}
              maxHeight={560}
              submitOnEnter
            />
          </div>
        </section>

        <section className="aurora-rich-demo-panel min-h-0 overflow-auto p-4">
          <div className="aurora-rich-demo-panel-title">
            <Eye className="h-4 w-4" />
            <span>实时预览</span>
          </div>
          <Markdown content={value} />
        </section>
      </div>

      <div className="aurora-rich-demo-raw mx-auto w-full max-w-6xl">
        <div className="aurora-rich-demo-panel-title">
          <Code2 className="h-4 w-4" />
          <span>原始内容</span>
        </div>
        <pre className="max-h-44 overflow-auto p-3 text-xs leading-5">{value}</pre>
      </div>
    </div>
  )
}
