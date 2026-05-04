import { useState, useRef, useEffect } from 'react'
import { fetchSSE } from '@/api/sse'
import { Markdown } from '@/components/shared/Markdown'

export default function QuestionEvaluatePage() {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState('')
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => { abortRef.current?.abort() }, [])

  const evaluate = async () => {
    if (!question.trim() || loading) return
    setResult('')
    setLoading(true)
    abortRef.current = new AbortController()
    try {
      await fetchSSE('/api/question-evaluate/stream', { question }, (chunk) => setResult((c) => c + chunk), abortRef.current.signal)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 space-y-4 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">好题鉴别</h1>
      <textarea
        className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
        rows={5}
        placeholder="粘贴题目内容..."
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
      />
      <button onClick={evaluate} disabled={loading} className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50">
        {loading ? '鉴别中...' : '开始鉴别'}
      </button>
      {result && <div className="border rounded-lg p-4 bg-card"><Markdown content={result} /></div>}
    </div>
  )
}
