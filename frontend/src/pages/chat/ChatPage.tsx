import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, Square } from 'lucide-react'
import { chatApi } from '@/api/chat'
import { fetchSSE } from '@/api/sse'
import { MarkdownRenderer } from '@/components/MarkdownRenderer'
import { cn } from '@/lib/utils'

interface Message { role: 'user' | 'assistant'; content: string }

export default function ChatPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const { data: history } = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => chatApi.getMessages(conversationId!).then((r) => r.data),
    enabled: !!conversationId,
  })

  useEffect(() => { if (history?.messages) setMessages(history.messages) }, [history])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])
  useEffect(() => () => { abortRef.current?.abort() }, [])

  const autoResize = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  const send = async () => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setMessages((m) => [...m, { role: 'user', content: text }])
    setStreaming(true)
    setMessages((m) => [...m, { role: 'assistant', content: '' }])
    abortRef.current = new AbortController()
    try {
      await fetchSSE('/api/chat', { message: text, conversation_id: conversationId }, (chunk) => {
        setMessages((m) => {
          const last = m[m.length - 1]
          return [...m.slice(0, -1), { ...last, content: last.content + chunk }]
        })
      }, abortRef.current.signal)
      qc.invalidateQueries({ queryKey: ['conversations'] })
      if (!conversationId) navigate('/chat', { replace: true })
    } catch (e: unknown) {
      if ((e as Error).name !== 'AbortError')
        setMessages((m) => [...m.slice(0, -1), { role: 'assistant', content: '发生错误，请重试。' }])
    } finally {
      setStreaming(false)
    }
  }

  const stop = () => { abortRef.current?.abort(); setStreaming(false) }

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <p className="text-2xl font-semibold">有什么可以帮你的？</p>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto w-full px-4 py-8 space-y-8">
            {messages.map((msg, i) => (
              <div key={i} className={cn(msg.role === 'user' ? 'flex justify-end' : '')}>
                {msg.role === 'user' ? (
                  <div className="bg-muted rounded-3xl px-5 py-3 max-w-[85%] text-sm whitespace-pre-wrap">
                    {msg.content}
                  </div>
                ) : (
                  <div className="text-sm leading-7">
                    <MarkdownRenderer content={msg.content || (streaming && i === messages.length - 1 ? '▋' : '')} />
                  </div>
                )}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-4 pb-4 pt-2">
        <div className="max-w-3xl mx-auto">
          <div className="relative border bg-background rounded-3xl shadow-sm focus-within:ring-2 focus-within:ring-ring transition-shadow">
            <textarea
              ref={textareaRef}
              rows={1}
              className="w-full resize-none bg-transparent px-5 py-4 pr-14 text-sm focus:outline-none leading-relaxed max-h-[200px]"
              placeholder="给试卷助手发消息"
              value={input}
              onChange={(e) => { setInput(e.target.value); autoResize() }}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            />
            <div className="absolute right-3 bottom-3">
              {streaming ? (
                <button onClick={stop} className="w-8 h-8 rounded-full bg-foreground text-background flex items-center justify-center hover:opacity-80 transition-opacity">
                  <Square size={13} fill="currentColor" />
                </button>
              ) : (
                <button
                  onClick={send}
                  disabled={!input.trim()}
                  className="w-8 h-8 rounded-full bg-foreground text-background flex items-center justify-center disabled:opacity-30 hover:opacity-80 transition-opacity"
                >
                  <ArrowUp size={15} strokeWidth={2.5} />
                </button>
              )}
            </div>
          </div>
          <p className="text-center text-xs text-muted-foreground mt-2">AI 可能会出错，请核实重要信息。</p>
        </div>
      </div>
    </div>
  )
}
