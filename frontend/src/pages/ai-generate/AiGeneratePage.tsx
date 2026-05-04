import { useState, useRef, useEffect } from 'react'
import { fetchSSE } from '@/api/sse'
import { Markdown } from '@/components/shared/Markdown'

export default function AiGeneratePage() {
  const [config, setConfig] = useState({ subject: '', count: 5, type: '选择题' })
  const [result, setResult] = useState('')
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => { abortRef.current?.abort() }, [])

  const generate = async () => {
    if (loading) return
    setResult('')
    setLoading(true)
    abortRef.current = new AbortController()
    try {
      await fetchSSE('/api/ai-generate/stream', config, (chunk) => setResult((c) => c + chunk), abortRef.current.signal)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full">
      <div className="w-72 border-r p-4 space-y-4 shrink-0">
        <h2 className="font-semibold">AI出题</h2>
        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium">科目</label>
            <input className="mt-1 w-full border rounded-md px-3 py-2 text-sm bg-background" value={config.subject} onChange={(e) => setConfig((c) => ({ ...c, subject: e.target.value }))} />
          </div>
          <div>
            <label className="text-sm font-medium">题型</label>
            <select className="mt-1 w-full border rounded-md px-3 py-2 text-sm bg-background" value={config.type} onChange={(e) => setConfig((c) => ({ ...c, type: e.target.value }))}>
              {['选择题', '填空题', '解答题', '判断题'].map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="text-sm font-medium">数量</label>
            <input type="number" min={1} max={20} className="mt-1 w-full border rounded-md px-3 py-2 text-sm bg-background" value={config.count} onChange={(e) => setConfig((c) => ({ ...c, count: Number(e.target.value) }))} />
          </div>
          <button onClick={generate} disabled={loading} className="w-full py-2 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50">
            {loading ? '生成中...' : '开始生成'}
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-6">
        {result ? <Markdown content={result} /> : <div className="text-muted-foreground text-sm">配置参数后点击生成</div>}
      </div>
    </div>
  )
}
