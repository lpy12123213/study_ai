import { useRef, useState } from 'react'
import { BookOpen, Loader2, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { fetchSSE } from '@/api/client'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn, generateId } from '@/lib/utils'
import type { TaskStep } from '@/types'

type StudyMaterialsAgentEvent =
  | { event: 'thinking'; data: { content?: unknown } }
  | { event: 'tool_call'; data: { name?: unknown; arguments?: unknown } }
  | { event: 'content'; data: { content?: unknown; section?: unknown } }
  | { event: 'done'; data: { material?: unknown } }
  | { event: 'error'; data: { message?: unknown } }
  | { event: string; data?: unknown }

function toText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export default function StudyMaterialsPage() {
  const [query, setQuery] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [steps, setSteps] = useState<TaskStep[]>([])

  const {
    startTask,
    addStep,
    updateStep,
    completeTask,
    failTask,
  } = useTaskStore()

  const runningStepIdRef = useRef<string | null>(null)
  const taskIdRef = useRef<string | null>(null)

  const startRunningStep = (title: string, extra?: Partial<TaskStep>) => {
    const t = new Date().toISOString()

    // Complete previous running step
    const prevId = runningStepIdRef.current
    if (prevId) {
      updateStep(taskIdRef.current!, prevId, { status: 'completed', endTime: t })
      setSteps((prev) => prev.map((s) => (s.id === prevId ? { ...s, status: 'completed', endTime: t } : s)))
    }

    const step: TaskStep = {
      id: generateId(),
      title,
      status: 'running',
      startTime: t,
      ...extra,
    }
    runningStepIdRef.current = step.id

    addStep(taskIdRef.current!, step)
    setSteps((prev) => [...prev, step])
  }

  const handleGenerate = () => {
    const q = query.trim()
    if (!q) return

    setError(null)
    setContent('')
    setSteps([])
    setIsGenerating(true)

    const taskId = `study-materials-${Date.now()}`
    taskIdRef.current = taskId
    runningStepIdRef.current = null
    startTask(taskId)

    startRunningStep('接收请求并开始生成…')

    let done = false
    let pendingText = ''
    let flushTimer: number | null = null

    const flush = () => {
      if (!pendingText) return
      setContent((prev) => prev + pendingText)
      pendingText = ''
    }

    void fetchSSE(
      '/study-materials/generate',
      { query: q },
      (data) => {
        const evt = data as StudyMaterialsAgentEvent
        const kind = typeof (evt as any)?.event === 'string' ? (evt as any).event : ''
        const payload = (evt as any)?.data

        if (kind === 'thinking') {
          const text = toText(payload?.content) || '思考中…'
          startRunningStep(text)
          return
        }

        if (kind === 'tool_call') {
          const name = toText(payload?.name) || 'tool'
          startRunningStep(`调用工具：${name}`, { toolName: name, input: payload?.arguments })
          return
        }

        if (kind === 'content') {
          const chunk = toText(payload?.content)
          if (chunk) {
            pendingText += chunk
            if (flushTimer == null) {
              flushTimer = window.setTimeout(() => {
                flushTimer = null
                flush()
              }, 60)
            }
          }
          return
        }

        if (kind === 'done') {
          done = true
          if (flushTimer != null) {
            window.clearTimeout(flushTimer)
            flushTimer = null
          }
          flush()

          const t = new Date().toISOString()
          const lastId = runningStepIdRef.current
          if (lastId) {
            updateStep(taskId, lastId, { status: 'completed', endTime: t })
            setSteps((prev) => prev.map((s) => (s.id === lastId ? { ...s, status: 'completed', endTime: t } : s)))
          }

          const md = toText(payload?.material?.markdown) || ''
          if (md) setContent(md)

          completeTask(taskId)
          setIsGenerating(false)
          return
        }

        if (kind === 'error') {
          done = true
          const msg = toText(payload?.message) || '生成失败'
          setError(msg)
          failTask(taskId, msg)
          setIsGenerating(false)
        }
      },
      (err) => {
        if (done) return
        const msg = err.message || '生成失败'
        setError(msg)
        failTask(taskId, msg)
        setIsGenerating(false)
      },
      () => {
        if (!done) {
          completeTask(taskId)
          setIsGenerating(false)
        }
      }
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Top bar */}
      <div className="border-b border-border p-3 glass flex items-center justify-between">
        <div className="text-sm font-medium text-muted-foreground">
          自学资料生成 · Plan-Act-Reflect
        </div>
        <Button
          onClick={handleGenerate}
          disabled={isGenerating || !query.trim()}
          className="gap-2"
          size="sm"
        >
          {isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          生成
        </Button>
      </div>

      <div className="flex-1 overflow-auto p-4">
        <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Left: input + steps */}
          <div className="lg:col-span-2 space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <BookOpen className="h-4 w-4" />
                  今天想学什么？
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="例如：函数单调性 / 二次函数最值 / 受力分析 / 化学平衡常数…"
                  className="min-h-[110px]"
                  disabled={isGenerating}
                />

                {error && (
                  <div className="text-sm text-destructive">
                    出错：{error}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">执行步骤</CardTitle>
              </CardHeader>
              <CardContent>
                <TaskTimeline steps={steps} />
              </CardContent>
            </Card>
          </div>

          {/* Right: preview */}
          <div className="lg:col-span-3">
            <Card className={cn(isGenerating && 'border-foreground/30')}>
              <CardHeader>
                <CardTitle className="text-base">Markdown 预览（纯文本）</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="whitespace-pre-wrap text-sm leading-6 min-h-[260px]">
                  {content || (isGenerating ? '生成中…' : '（暂无内容）')}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}

