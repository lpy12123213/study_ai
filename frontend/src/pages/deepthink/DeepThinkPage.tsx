import { useState, useRef, useEffect } from 'react'
import { fetchSSE } from '@/api/sse'
import { MarkdownRenderer } from '@/components/MarkdownRenderer'

export default function DeepThinkPage() {
  const [problem, setProblem] = useState('')
  const [result, setResult] = useState('')
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => { abortRef.current?.abort() }, [])

  const solve = async () => {
    if (!problem.trim() || loading) return
    setResult('')
    setLoading(true)
    abortRef.current = new AbortController()
    try {
      await fetchSSE('/api/deepthink/solve', { problem }, (chunk) => setResult((c) => c + chunk), abortRef.current.signal)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 space-y-4 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">深度解题</h1>
      <textarea
        className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
        rows={4}
        placeholder="输入题目..."
        value={problem}
        onChange={(e) => setProblem(e.target.value)}
      />
      <button onClick={solve} disabled={loading} className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50">
        {loading ? '解题中...' : '开始解题'}
      </button>
      {result && <div className="border rounded-lg p-4 bg-card"><MarkdownRenderer content={result} /></div>}
    </div>
  )
}
