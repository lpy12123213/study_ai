import { useState } from 'react'
import { feedbackApi } from '@/api/feedback'

export default function FeedbackPage() {
  const [content, setContent] = useState('')
  const [sent, setSent] = useState(false)

  const submit = async () => {
    if (!content.trim()) return
    await feedbackApi.submit({ content })
    setSent(true)
  }

  if (sent) return <div className="text-center py-12 text-muted-foreground">感谢您的反馈！</div>

  return (
    <div className="space-y-4 max-w-xl">
      <h1 className="text-2xl font-semibold">反馈</h1>
      <textarea className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring" rows={6} placeholder="请描述您的问题或建议..." value={content} onChange={(e) => setContent(e.target.value)} />
      <button onClick={submit} disabled={!content.trim()} className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50">提交</button>
    </div>
  )
}
