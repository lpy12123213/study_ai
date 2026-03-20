import { BookOpenText, FileClock, Library, Orbit, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { humanizeAiGenerateTaskError } from '@/pages/aiGenerate/humanizeTaskError'

interface ContextRailProps {
  missionText: string
  subject: string
  difficulty: string
  count: string
  questionType: string
  useStudyArchive: boolean
  progress: number
  stage: string
  taskStatus: string
  taskError?: string
  draftCount: number
  confirmedCount: number
  libraryTotal: number
  onScrollToDraft: (index: number) => void
}

function statusVariant(taskStatus: string): 'secondary' | 'destructive' | 'outline' {
  const status = String(taskStatus || '').trim()
  if (status === 'failed') return 'destructive'
  if (status === 'running' || status === 'completed') return 'secondary'
  return 'outline'
}

export function ContextRail(props: ContextRailProps) {
  const {
    missionText,
    subject,
    difficulty,
    count,
    questionType,
    useStudyArchive,
    progress,
    stage,
    taskStatus,
    taskError,
    draftCount,
    confirmedCount,
    libraryTotal,
    onScrollToDraft,
  } = props

  const errorInfo = humanizeAiGenerateTaskError(taskError || '')
  const errorText = String(errorInfo.display || '').trim()

  return (
    <Card className="rounded-[32px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(246,241,231,0.92))] shadow-[0_20px_50px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(26,28,42,0.92),rgba(18,20,30,0.92))] dark:shadow-[0_20px_70px_rgba(0,0,0,0.55)]">
      <CardHeader className="border-b border-border/60 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
            <Orbit className="h-5 w-5" />
          </div>
          <div>
            <CardTitle className="text-lg">本次任务</CardTitle>
            <div className="text-sm text-muted-foreground">摘要、进度、资料引用与草稿跳转。</div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-4 lg:p-6">
        <div className="rounded-[24px] border border-border/70 bg-background/80 p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="text-xs uppercase tracking-[0.24em] text-muted-foreground">Progress</div>
            <Badge variant={statusVariant(taskStatus)} className="rounded-full px-2.5 py-1 text-[11px]">
              {taskStatus || 'idle'}
            </Badge>
          </div>
          <div className="mt-3 text-3xl font-semibold">{Math.round(progress)}%</div>
          <Progress value={progress} className="mt-3 h-2" />
          <div className="mt-3 text-sm text-muted-foreground">{stage || '等待启动生成任务'}</div>
          {taskStatus === 'failed' && errorText ? (
            <div className="mt-3 rounded-[18px] border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              <div>{errorText}</div>
              {errorInfo.code ? (
                <code className="mt-2 block w-fit rounded-full border border-destructive/20 bg-destructive/10 px-3 py-1 font-mono text-xs text-destructive/90">
                  {errorInfo.code}
                </code>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="rounded-[24px] border border-border/70 bg-background/80 p-4">
          <div className="text-xs uppercase tracking-[0.24em] text-muted-foreground">Mission</div>
          <div className="mt-3 text-sm leading-6 text-foreground/88">{missionText || '尚未填写任务描述。'}</div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge variant="outline" className="rounded-full">{subject || '未选择学科'}</Badge>
            <Badge variant="outline" className="rounded-full">{difficulty || '难度不限'}</Badge>
            <Badge variant="outline" className="rounded-full">{count || '5'} 题</Badge>
            <Badge variant="outline" className="rounded-full">{questionType || '题型不限'}</Badge>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
          <div className="rounded-[22px] border border-border/70 bg-background/80 p-4">
            <div className="flex items-center gap-2 text-sm font-medium"><FileClock className="h-4 w-4" /> 草稿数</div>
            <div className="mt-2 text-2xl font-semibold">{draftCount}</div>
          </div>
          <div className="rounded-[22px] border border-border/70 bg-background/80 p-4">
            <div className="flex items-center gap-2 text-sm font-medium"><Sparkles className="h-4 w-4" /> 已确认</div>
            <div className="mt-2 text-2xl font-semibold">{confirmedCount}</div>
          </div>
          <div className="rounded-[22px] border border-border/70 bg-background/80 p-4">
            <div className="flex items-center gap-2 text-sm font-medium"><Library className="h-4 w-4" /> AI 题库</div>
            <div className="mt-2 text-2xl font-semibold">{libraryTotal}</div>
          </div>
        </div>

        <div className="rounded-[24px] border border-border/70 bg-background/80 p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <BookOpenText className="h-4 w-4" />
            资料引用
          </div>
          <div className="mt-2 text-sm text-muted-foreground">
            {useStudyArchive ? '已启用 Study Archive 辅助上下文。' : '当前未引用 Study Archive。'}
          </div>
        </div>

        <div className="rounded-[24px] border border-border/70 bg-background/80 p-4">
          <div className="text-sm font-medium">快速跳转</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {Array.from({ length: draftCount }).map((_, index) => (
              <Button
                key={`jump-${index}`}
                type="button"
                variant="outline"
                size="sm"
                className="rounded-full"
                onClick={() => onScrollToDraft(index)}
              >
                {`题目 ${String(index + 1).padStart(2, '0')}`}
              </Button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
