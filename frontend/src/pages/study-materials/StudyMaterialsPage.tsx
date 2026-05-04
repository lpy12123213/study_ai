import { useState, useRef, useEffect } from 'react'
import { fetchSSE } from '@/api/sse'
import { Markdown } from '@/components/shared/Markdown'

export default function StudyMaterialsPage() {
  const [topic, setTopic] = useState('')
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => { abortRef.current?.abort() }, [])

  const generate = async () => {
    if (!topic.trim() || loading) return
    setContent('')
    setLoading(true)
    abortRef.current = new AbortController()
    try {
      await fetchSSE('/api/study-materials/generate', { topic }, (chunk) => setContent((c) => c + chunk), abortRef.current.signal)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 space-y-4 max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold">自学资料</h1>
      <div className="flex gap-2">
        <input
          className="flex-1 border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="输入主题..."
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && generate()}
        />
        <button onClick={generate} disabled={loading} className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50">
          {loading ? '生成中...' : '生成'}
        </button>
      </div>
      {content && <div className="border rounded-lg p-4 bg-card"><Markdown content={content} /></div>}
    </div>
  )
}
