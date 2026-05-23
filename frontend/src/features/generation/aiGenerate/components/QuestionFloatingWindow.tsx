import { useEffect, useState } from 'react'
import { Loader2, PanelRightClose, PanelRightOpen, Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { GenerationStream } from '@/features/generation/aiGenerate/GenerationStream'
import type { AiGenerateDraftCard, AiGenerateStudioSession } from '@/features/generation/aiGenerate/types'

interface QuestionFloatingWindowProps {
  open: boolean
  session: AiGenerateStudioSession | null
  isGenerating: boolean
  isFetching: boolean
  draftRefs: React.MutableRefObject<Array<HTMLDivElement | null>>
  onOpen: () => void
  onClose: () => void
  onConfirm: (questionId: string) => void
  onRegenerateSection: (questionId: string, sectionKey: keyof AiGenerateDraftCard['sections']) => void
  onSectionChange: (questionId: string, sectionKey: keyof AiGenerateDraftCard['sections'], content: string) => void
  onToggleSectionLock: (questionId: string, sectionKey: keyof AiGenerateDraftCard['sections']) => void
}

function EmptyQuestionWindow({ isFetching }: { isFetching: boolean }) {
  return (
    <div className="flex h-full items-center justify-center rounded-[28px] border border-dashed border-border bg-background/70 px-6 text-center">
      <div className="max-w-md space-y-3">
        {isFetching ? <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" /> : null}
        <div className="text-lg font-semibold">{isFetching ? '正在加载题目…' : '题目会在这里出现'}</div>
        <div className="text-sm leading-6 text-muted-foreground">
          在主页面填写出题任务并开始生成后，草稿题目、答案、解析和审核入库操作都会集中显示在这个悬浮窗里。
        </div>
      </div>
    </div>
  )
}

export function QuestionFloatingWindow(props: QuestionFloatingWindowProps) {
  const [locallyClosed, setLocallyClosed] = useState(false)
  const draftCount = props.session?.drafts.length || 0
  const statusLabel = props.isGenerating ? '生成中' : draftCount > 0 ? `${draftCount} 道题` : '等待生成'
  const visible = props.open && !locallyClosed

  useEffect(() => {
    if (props.open) setLocallyClosed(false)
  }, [props.open])

  if (!visible) {
    return (
      <Button
        type="button"
        aria-label="打开题目悬浮窗"
        className="fixed bottom-6 right-6 z-40 h-12 rounded-full px-4 shadow-[0_18px_45px_rgba(15,23,42,0.24)]"
        onClick={() => {
          setLocallyClosed(false)
          props.onOpen()
        }}
      >
        <PanelRightOpen className="h-4 w-4" />
        <span>题目悬浮窗</span>
        <Badge variant="secondary" className="ml-1 rounded-full bg-primary-foreground/15 text-primary-foreground">
          {statusLabel}
        </Badge>
      </Button>
    )
  }

  return (
    <aside
      aria-label="题目悬浮窗"
      className="fixed inset-x-3 bottom-3 top-3 z-40 flex flex-col overflow-hidden rounded-[30px] border border-border/70 bg-background/95 shadow-[0_28px_80px_rgba(15,23,42,0.28)] backdrop-blur-xl sm:inset-x-auto sm:right-4 sm:w-[min(760px,calc(100vw-2rem))] lg:right-6 lg:top-6 lg:bottom-6"
    >
      <div className="flex items-start justify-between gap-4 border-b border-border/70 bg-background/80 px-5 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">题目悬浮窗</h2>
              <div className="mt-0.5 text-sm text-muted-foreground">生成的题目、答案、解析和审核操作集中在这里。</div>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant="outline" className="rounded-full">
            {statusLabel}
          </Badge>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="收起题目悬浮窗"
            onClick={() => {
              setLocallyClosed(true)
              props.onClose()
            }}
          >
            <PanelRightClose className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden p-4">
        {props.session ? (
          <GenerationStream
            sessionId={props.session.sessionId}
            drafts={props.session.drafts}
            getDraftRef={(index) => (node) => {
              props.draftRefs.current[index] = node
            }}
            onConfirm={props.onConfirm}
            onRegenerateSection={props.onRegenerateSection}
            onSectionChange={props.onSectionChange}
            onToggleSectionLock={props.onToggleSectionLock}
          />
        ) : (
          <EmptyQuestionWindow isFetching={props.isFetching} />
        )}
      </div>
    </aside>
  )
}
