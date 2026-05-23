import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Download, Film, Loader2, Play, RotateCcw, ShieldCheck, Video } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { downloadObjectUrl, downloadText } from '@/api/client'
import { generateKnowledgeVideo, type KnowledgeVideoTaskResult } from '@/api/knowledgeVideos'
import { getTask, streamTask, type TaskStreamEvent } from '@/api/tasks'
import { taskEventToStep, upsertTaskStep } from '@/components/task/taskEventAdapter'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import type { TaskStep } from '@/types'

type Status = 'idle' | 'running' | 'completed' | 'failed'

function toStringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function isAbortError(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'name' in error && String(error.name) === 'AbortError'
}

function downloadByUrl(url: string): void {
  void downloadObjectUrl(url).then(({ objectUrl, revoke, filename }) => {
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = filename || ''
    a.click()
    window.setTimeout(revoke, 60_000)
  })
}

function toDisplayStageLabel(label: string): string {
  const text = label.trim()
  if (!text) return ''
  return text
    .replace(/Docker\s*沙盒渲染/gi, '安全渲染中')
    .replace(/Docker\s*沙盒/gi, '安全渲染环境')
    .replace(/Manim\s*源码/gi, '生成脚本')
    .replace(/Manim/gi, '动画生成')
}

export default function KnowledgeVideoPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [topic, setTopic] = useState(() => searchParams.get('topic') || '')
  const [subject, setSubject] = useState(() => searchParams.get('subject') || '')
  const [sourceArchiveId, setSourceArchiveId] = useState(() => searchParams.get('source_archive_id') || '')
  const [sourceMarkdown, setSourceMarkdown] = useState(() => searchParams.get('source_markdown') || '')
  const [durationSeconds, setDurationSeconds] = useState('30')
  const [style, setStyle] = useState('clean')
  const [quality, setQuality] = useState('low')
  const [requirements, setRequirements] = useState('')

  const [taskId, setTaskId] = useState('')
  const [status, setStatus] = useState<Status>('idle')
  const [progress, setProgress] = useState(0)
  const [currentStage, setCurrentStage] = useState('安全渲染环境')
  const [steps, setSteps] = useState<TaskStep[]>([])
  const [result, setResult] = useState<KnowledgeVideoTaskResult | null>(null)
  const [error, setError] = useState('')
  const [videoObjectUrl, setVideoObjectUrl] = useState('')
  const [scriptText, setScriptText] = useState('')
  const [scriptError, setScriptError] = useState('')
  const videoRevokeRef = useRef<(() => void) | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
      videoRevokeRef.current?.()
    }
  }, [])

  useEffect(() => {
    if (!result?.video_url) {
      setVideoObjectUrl('')
      return
    }
    let active = true
    videoRevokeRef.current?.()
    videoRevokeRef.current = null
    setVideoObjectUrl('')
    void downloadObjectUrl(result.video_url).then(({ objectUrl, revoke }) => {
      if (!active) {
        revoke()
        return
      }
      videoRevokeRef.current = revoke
      setVideoObjectUrl(objectUrl)
    })
    return () => {
      active = false
    }
  }, [result?.video_url])

  useEffect(() => {
    if (!result?.script_url) {
      setScriptText('')
      setScriptError('')
      return
    }
    const controller = new AbortController()
    setScriptText('')
    setScriptError('')
    void downloadText(result.script_url, { signal: controller.signal })
      .then(setScriptText)
      .catch((err) => {
        if (isAbortError(err)) return
        setScriptError(err instanceof Error ? err.message : '脚本加载失败')
      })
    return () => controller.abort()
  }, [result?.script_url])

  const canSubmit = useMemo(() => topic.trim().length > 0 && status !== 'running', [topic, status])

  const finishFromTask = async (id: string) => {
    const task = await getTask(id)
    const nextStatus = String((task as any)?.status || '')
    if (nextStatus === 'completed') {
      setStatus('completed')
      setProgress(100)
      setResult(((task as any)?.result || {}) as KnowledgeVideoTaskResult)
      return
    }
    if (nextStatus === 'failed' || nextStatus === 'canceled' || nextStatus === 'cancelled') {
      setStatus('failed')
      const err = (task as any)?.error
      setError(toStringValue((err as any)?.message) || toStringValue((err as any)?.error) || '生成失败')
    }
  }

  const startStream = (id: string) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    streamTask(
      id,
      0,
      (evt: TaskStreamEvent) => {
        if (evt.type === 'progress') {
          const data = evt.data && typeof evt.data === 'object' ? evt.data : {}
          const p = Number((data as any).progress || 0)
          if (Number.isFinite(p)) setProgress(Math.max(0, Math.min(100, p)))
          const stageLabel = toStringValue((data as any).stage_label) || toStringValue((data as any).stage)
          if (stageLabel) setCurrentStage(toDisplayStageLabel(stageLabel))
        }
        const step = taskEventToStep(evt)
        if (step) setSteps((prev) => upsertTaskStep(prev, step))
        if (evt.type === 'error') {
          setStatus('failed')
          const data = evt.data && typeof evt.data === 'object' ? evt.data : {}
          setError(String((data as any).error || (data as any).message || '生成失败'))
        }
      },
      (err) => {
        setStatus('failed')
        setError(err.message || 'stream_error')
      },
      () => {
        void finishFromTask(id)
      },
      { signal: controller.signal }
    )
  }

  const handleSubmit = async () => {
    if (!canSubmit) return
    setStatus('running')
    setProgress(0)
    setCurrentStage('任务创建中')
    setSteps([])
    setResult(null)
    setError('')
    setScriptText('')
    setScriptError('')

    const archiveId = Number(sourceArchiveId)
    const duration = Number(durationSeconds)
    const payload = {
      topic: topic.trim(),
      subject: subject.trim() || undefined,
      source_markdown: sourceMarkdown.trim() || undefined,
      source_archive_id: Number.isFinite(archiveId) && archiveId > 0 ? Math.floor(archiveId) : undefined,
      duration_seconds: Number.isFinite(duration) ? Math.max(10, Math.min(180, Math.floor(duration))) : 30,
      style,
      quality,
      requirements: requirements.trim() || undefined,
    }

    try {
      const { taskId: id } = await generateKnowledgeVideo(payload)
      if (!id) throw new Error('missing_task_id')
      setTaskId(id)
      const next = new URLSearchParams(searchParams)
      next.set('task', id)
      setSearchParams(next, { replace: true })
      startStream(id)
    } catch (err) {
      setStatus('failed')
      setError(err instanceof Error ? err.message : '生成失败')
    }
  }

  const reset = () => {
    abortRef.current?.abort()
    setStatus('idle')
    setProgress(0)
    setCurrentStage('安全渲染环境')
    setSteps([])
    setResult(null)
    setError('')
    setScriptText('')
    setScriptError('')
    setTaskId('')
  }

  return (
    <div className="h-full min-h-0 flex flex-col bg-background">
      <div className="border-b border-border p-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Film className="h-5 w-5 text-primary shrink-0" />
          <div className="font-semibold truncate">知识视频</div>
          {status === 'running' && <Badge variant="secondary">生成中</Badge>}
          {status === 'completed' && <Badge>已完成</Badge>}
          {status === 'failed' && <Badge variant="destructive">失败</Badge>}
        </div>
        <div className="flex items-center gap-2">
          {taskId && <span className="text-xs font-mono text-muted-foreground">{taskId}</span>}
          <Button type="button" variant="outline" size="sm" onClick={reset} disabled={status === 'running'}>
            <RotateCcw className="h-4 w-4 mr-2" />
            重置
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-4 p-4 overflow-hidden">
        <Card className="min-h-0 flex flex-col">
          <ScrollArea className="flex-1">
            <div className="p-4 space-y-4">
              <label className="block space-y-1.5">
                <span className="text-sm font-medium">主题</span>
                <Input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="导数的几何意义" />
              </label>

              <label className="block space-y-1.5">
                <span className="text-sm font-medium">学科</span>
                <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="高中数学" />
              </label>

              <div className="grid grid-cols-3 gap-3">
                <label className="block space-y-1.5">
                  <span className="text-sm font-medium">时长</span>
                  <Input value={durationSeconds} onChange={(e) => setDurationSeconds(e.target.value)} inputMode="numeric" />
                </label>
                <label className="block space-y-1.5">
                  <span className="text-sm font-medium">风格</span>
                  <select
                    className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                    value={style}
                    onChange={(e) => setStyle(e.target.value)}
                  >
                    <option value="clean">clean</option>
                    <option value="chalkboard">chalkboard</option>
                    <option value="minimal">minimal</option>
                    <option value="colorful">colorful</option>
                  </select>
                </label>
                <label className="block space-y-1.5">
                  <span className="text-sm font-medium">质量</span>
                  <select
                    className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                    value={quality}
                    onChange={(e) => setQuality(e.target.value)}
                  >
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                  </select>
                </label>
              </div>

              <label className="block space-y-1.5">
                <span className="text-sm font-medium">归档 ID</span>
                <Input value={sourceArchiveId} onChange={(e) => setSourceArchiveId(e.target.value)} inputMode="numeric" />
              </label>

              <label className="block space-y-1.5">
                <span className="text-sm font-medium">参考资料</span>
                <Textarea
                  value={sourceMarkdown}
                  onChange={(e) => setSourceMarkdown(e.target.value)}
                  className="min-h-32"
                />
              </label>

              <label className="block space-y-1.5">
                <span className="text-sm font-medium">额外要求</span>
                <Textarea value={requirements} onChange={(e) => setRequirements(e.target.value)} className="min-h-24" />
              </label>
            </div>
          </ScrollArea>

          <div className="border-t border-border p-4">
            <Button type="button" className="w-full" disabled={!canSubmit} onClick={handleSubmit}>
              {status === 'running' ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Play className="h-4 w-4 mr-2" />}
              生成视频
            </Button>
          </div>
        </Card>

        <div className="min-h-0 grid grid-rows-[auto_1fr] gap-4">
          <Card className="p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 font-medium">
                <ShieldCheck className="h-4 w-4 text-primary" />
                {currentStage}
              </div>
              <div className="text-sm text-muted-foreground">{Math.round(progress)}%</div>
            </div>
            <Progress value={progress} />
            {error && <div className="text-sm text-destructive whitespace-pre-wrap break-words">{error}</div>}
          </Card>

          <div className="min-h-0 grid grid-cols-1 2xl:grid-cols-[1fr_380px] gap-4 overflow-hidden">
            <Card className="min-h-0 flex flex-col overflow-hidden">
              <div className="border-b border-border p-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 font-medium">
                  <Video className="h-4 w-4 text-primary" />
                  预览
                </div>
                <div className="flex items-center gap-2">
                  {result?.video_url && (
                    <Button type="button" size="sm" variant="outline" onClick={() => downloadByUrl(result.video_url || '')}>
                      <Download className="h-4 w-4 mr-2" />
                      下载视频
                    </Button>
                  )}
                  {result?.subtitle_url && (
                    <Button type="button" size="sm" variant="outline" onClick={() => downloadByUrl(result.subtitle_url || '')}>
                      <Download className="h-4 w-4 mr-2" />
                      下载字幕
                    </Button>
                  )}
                </div>
              </div>

              <div className="flex-1 min-h-0 p-4">
                {videoObjectUrl ? (
                  <video className="h-full w-full bg-black rounded-md" src={videoObjectUrl} controls />
                ) : (
                  <div className="h-full min-h-64 rounded-md border border-dashed border-border flex items-center justify-center text-sm text-muted-foreground">
                    {status === 'running' ? '渲染中…' : '等待视频'}
                  </div>
                )}
              </div>

              {result?.script_url && (
                <div className="border-t border-border p-3 space-y-2">
                  <div className="text-xs text-muted-foreground flex items-center justify-between gap-3">
                    <span className="font-mono break-all">{result.script_url}</span>
                    <Button type="button" size="sm" variant="ghost" onClick={() => downloadByUrl(result.script_url || '')}>
                      脚本
                    </Button>
                  </div>
                  <div className="text-xs font-medium">生成脚本（只读）</div>
                  <ScrollArea className="h-40 rounded-md border border-border bg-muted/30">
                    <pre className="p-3 text-xs leading-relaxed whitespace-pre-wrap break-words font-mono">
                      {scriptText || scriptError || '脚本加载中'}
                    </pre>
                  </ScrollArea>
                </div>
              )}
            </Card>

            <Card className="min-h-0 overflow-hidden">
              <ScrollArea className="h-full">
                <div className="p-4">
                  <TaskTimeline steps={steps} />
                </div>
              </ScrollArea>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}
