import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, PanelsTopLeft, SquareArrowOutUpRight } from 'lucide-react'
import { Link } from 'react-router-dom'

import { TaskProgressHeader } from '@/components/task/TaskProgressHeader'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { taskEventToStep } from '@/components/task/taskEventAdapter'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { humanizeAiGenerateTaskError } from '@/features/generation/aiGenerate/humanizeTaskError'
import type { AiGenerateStudioSession } from '@/features/generation/aiGenerate/types'
import { statusLabel } from '@/features/generation/aiGenerate/studioUtils'
import { useTaskStore } from '@/stores/useTaskStore'
import type { TaskStep } from '@/types'


const EMPTY_TASK_STEPS: TaskStep[] = []

interface ReasonConsoleEntry {
  id: string
  label: '原始 Reason' | '事件 Trace'
  stageLabel: string
  content: string
  createdAt?: string
}

function toReasonEntries(
  session: AiGenerateStudioSession | null,
  currentTaskId: string,
  liveEvents: Array<{ type?: string; data?: any; created_at?: string; taskId?: string }>
): ReasonConsoleEntry[] {
  const entries: ReasonConsoleEntry[] = []
  const persistedEvents = Array.isArray(session?.taskEvents) ? session?.taskEvents || [] : []
  const statusEvents = [...persistedEvents, ...liveEvents].filter((event) => String(event?.type || '') === 'reasoning_status')
  const liveBlocks = liveEvents
    .filter((event) => String(event?.type || '') === 'reasoning_delta')
    .map((event, index) => ({
      id: `live-reason-${index}-${String(event.created_at || '')}`,
      taskId: String(event.taskId || '').trim(),
      stageLabel: String(event.data?.stage_label || event.data?.stage_id || '').trim() || '推理过程',
      source: String(event.data?.source || 'trace').trim() || 'trace',
      content: String(event.data?.content || '').trim(),
      createdAt: String(event.created_at || '').trim() || undefined,
    }))
    .filter((item) => item.content)

  const persistedBlocks = (session?.reasoningBlocks || []).filter((block) => {
    if (!currentTaskId || liveBlocks.length === 0) return true
    return String(block.taskId || '').trim() !== currentTaskId
  })

  function aggregateBlocks(
    blocks: Array<{ id: string; stageLabel?: string; source?: string; content: string; createdAt?: string }>
  ): ReasonConsoleEntry[] {
    const result: ReasonConsoleEntry[] = []
    let current: ReasonConsoleEntry | null = null
    let currentKey = ''
    for (const block of blocks) {
      const label: '原始 Reason' | '事件 Trace' = String(block.source || '').trim() === 'raw' ? '原始 Reason' : '事件 Trace'
      const stageLabel = String(block.stageLabel || '').trim() || '推理过程'
      const key = `${label}:${stageLabel}`
      if (current && key === currentKey) {
        current.content += String(block.content || '').trim()
      } else {
        if (current) result.push(current)
        current = {
          id: String(block.id || `${stageLabel}-${block.createdAt || ''}`),
          label,
          stageLabel,
          content: String(block.content || '').trim(),
          createdAt: block.createdAt,
        }
        currentKey = key
      }
    }
    if (current) result.push(current)
    return result
  }

  for (const event of statusEvents) {
    const mode = String(event?.data?.mode || 'trace').trim() || 'trace'
    const message = String(event?.data?.message || '').trim()
    if (!message) continue
    entries.push({
      id: `reason-status-${String(event.created_at || '')}-${mode}-${message}`,
      label: mode === 'raw' ? '原始 Reason' : '事件 Trace',
      stageLabel: String(event?.data?.stage_label || event?.data?.stage_id || '').trim() || '推理过程',
      content: message,
      createdAt: String(event.created_at || '').trim() || undefined,
    })
  }

  entries.push(...aggregateBlocks([...persistedBlocks, ...liveBlocks]))

  const deduped = new Map<string, ReasonConsoleEntry>()
  for (const entry of entries) {
    const key = `${entry.label}:${entry.stageLabel}:${entry.content.slice(0, 200)}`
    if (!deduped.has(key)) deduped.set(key, entry)
  }
  return [...deduped.values()].slice(-40)
}

interface StudioToolbarProps {
  activeSessionId: string
  currentTaskId: string
  session: AiGenerateStudioSession | null
  preferredTask: any | null
  taskEvents: Array<{ type?: string; data?: any; created_at?: string; taskId?: string }>
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function StudioToolbar(props: StudioToolbarProps) {
  const activeTasks = useTaskStore((state) => state.activeTasks)
  const [activeTab, setActiveTab] = useState<'timeline' | 'reason'>('timeline')
  const autoSwitchedToReasonRef = useRef(false)
  const activeTaskSteps = useMemo(
    () => (props.currentTaskId ? activeTasks.get(props.currentTaskId) || EMPTY_TASK_STEPS : EMPTY_TASK_STEPS),
    [activeTasks, props.currentTaskId]
  )

  const fallbackTaskSteps = useMemo(() => {
    const persisted = Array.isArray(props.session?.taskEvents) ? props.session?.taskEvents : []
    return persisted
      .map((item) =>
        taskEventToStep({
          taskId: String((item as any)?.taskId || props.currentTaskId),
          seq: Number((item as any)?.seq || 0),
          type: String((item as any)?.type || ''),
          data: (item as any)?.data,
          created_at: String((item as any)?.created_at || ''),
        })
      )
      .filter((item): item is TaskStep => Boolean(item))
  }, [props.currentTaskId, props.session?.taskEvents])

  const workflowSteps = activeTaskSteps.length > 0 ? activeTaskSteps : fallbackTaskSteps

  const progress = Math.max(0, Math.min(100, Number(props.preferredTask?.progress || (props.session?.status === 'committed' ? 100 : 0))))
  const stage = String(props.preferredTask?.stage || '').trim()
  const taskStatus = String(props.preferredTask?.status || '').trim()
  const sessionStatus = String(props.session?.status || '').trim()
  const isSessionRunning = sessionStatus === 'running'
  const effectiveTaskStatus = isSessionRunning ? 'running' : taskStatus || sessionStatus
  const taskError = String(props.preferredTask?.error || '').trim()
  const taskErrorInfo = useMemo(() => humanizeAiGenerateTaskError(taskError), [taskError])

  const reasonEntries = useMemo(
    () => toReasonEntries(props.session, props.currentTaskId, props.taskEvents),
    [props.currentTaskId, props.session, props.taskEvents]
  )

  useEffect(() => {
    if (reasonEntries.length > 0 && !autoSwitchedToReasonRef.current) {
      autoSwitchedToReasonRef.current = true
      setActiveTab('reason')
    }
  }, [reasonEntries.length])

  return (
    <Card className="overflow-hidden rounded-[30px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,244,234,0.94))] shadow-[0_22px_56px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(24,26,40,0.96),rgba(16,18,28,0.95))] dark:shadow-[0_24px_82px_rgba(0,0,0,0.56)]">
      <CardHeader className="border-b border-border/60 pb-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-200">
              <PanelsTopLeft className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-lg">流程工作栏</CardTitle>
              <div className="text-sm text-muted-foreground">同一视口内整合任务时间线、reason console 与任务中心跳转。</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button asChild type="button" variant="outline" size="sm" className="rounded-full">
              <Link to="/tasks">
                <SquareArrowOutUpRight className="h-3.5 w-3.5" />
                任务中心
              </Link>
            </Button>
            <Button type="button" variant="ghost" size="sm" className="rounded-full" onClick={() => props.onOpenChange(!props.open)}>
              <ChevronDown className={`h-4 w-4 transition-transform ${props.open ? '' : '-rotate-90'}`} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <Collapsible open={props.open} onOpenChange={props.onOpenChange}>
        <CollapsibleContent>
          <CardContent className="space-y-4 p-4 lg:p-6">
            <TaskProgressHeader taskId={props.currentTaskId || props.activeSessionId || undefined} />
            {taskStatus === 'failed' && !isSessionRunning && taskErrorInfo.display ? (
              <div className="rounded-[20px] border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                <div>{taskErrorInfo.display}</div>
                {taskErrorInfo.code ? (
                  <code className="mt-2 block w-fit rounded-full border border-destructive/20 bg-destructive/10 px-3 py-1 font-mono text-xs text-destructive/90">
                    {taskErrorInfo.code}
                  </code>
                ) : null}
              </div>
            ) : null}

            <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value === 'reason' ? 'reason' : 'timeline')}>
              <TabsList className="rounded-full">
                <TabsTrigger value="timeline" className="rounded-full">任务时间线</TabsTrigger>
                <TabsTrigger value="reason" className="rounded-full">
                  Reason Console
                  {reasonEntries.length > 0 && <Badge variant="outline" className="ml-1.5 rounded-full">{reasonEntries.length}</Badge>}
                </TabsTrigger>
              </TabsList>
              <TabsContent value="timeline" className="mt-3 rounded-[24px] border border-border/70 bg-background/80 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="text-sm text-muted-foreground">{stage || statusLabel(effectiveTaskStatus || sessionStatus || '')}</div>
                  <Badge variant="outline" className="rounded-full">进度 {Math.round(progress)}%</Badge>
                </div>
                <ScrollArea className="h-[240px] pr-3">
                  <TaskTimeline steps={workflowSteps} />
                </ScrollArea>
              </TabsContent>
              <TabsContent value="reason" className="mt-3 rounded-[24px] border border-border/70 bg-background/80 p-4">
                <ScrollArea className="h-[240px] pr-3">
                  {reasonEntries.length === 0 ? (
                    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">当前还没有 reasoning 片段。</div>
                  ) : (
                    <div className="space-y-3">
                      {reasonEntries.map((entry) => (
                        <div key={entry.id} className="rounded-[18px] border border-border/70 bg-background/70 p-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline" className="rounded-full">{entry.label}</Badge>
                            <Badge variant="outline" className="rounded-full">{entry.stageLabel}</Badge>
                          </div>
                          <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/90">{entry.content}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </ScrollArea>
              </TabsContent>
            </Tabs>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

