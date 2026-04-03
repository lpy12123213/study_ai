import { Loader2 } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { GenerationStream } from '@/pages/aiGenerate/GenerationStream'
import type { AiGenerateStudioSession } from '@/pages/aiGenerate/types'

interface DraftStreamProps {
  session: AiGenerateStudioSession | null
  isGenerating: boolean
  isFetching: boolean
  draftRefs: React.MutableRefObject<Array<HTMLDivElement | null>>
  onConfirm: (questionId: string) => void
  onRegenerateSection: (questionId: string, sectionKey: 'stem' | 'answer' | 'analysis') => void
  onSectionChange: (questionId: string, sectionKey: 'stem' | 'answer' | 'analysis', content: string) => void
  onToggleSectionLock: (questionId: string, sectionKey: 'stem' | 'answer' | 'analysis') => void
}

export function DraftStream(props: DraftStreamProps) {
  return (
    <Card className="overflow-hidden rounded-[30px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(247,242,232,0.92))] shadow-[0_22px_60px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(24,26,40,0.96),rgba(16,18,28,0.95))] dark:shadow-[0_24px_80px_rgba(0,0,0,0.56)]">
      <CardHeader className="border-b border-border/60 pb-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-lg">Draft Stream</CardTitle>
            <div className="mt-1 text-sm text-muted-foreground">恢复会话后可继续看见草稿、审查状态和局部重生成结果。</div>
          </div>
          {props.isGenerating ? (
            <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 dark:border-sky-800/70 dark:bg-sky-950/45 dark:text-sky-200">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              生成中
            </div>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="h-[720px] p-4 lg:p-6">
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
        ) : props.isFetching ? (
          <div className="flex h-full items-center justify-center rounded-[28px] border border-dashed border-border bg-background/60 px-6 text-center">
            <div className="max-w-xl space-y-3">
              <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
              <div className="text-sm text-muted-foreground">正在加载会话草稿…</div>
            </div>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center rounded-[28px] border border-dashed border-border bg-background/60 px-6 text-center">
            <div className="max-w-xl space-y-3">
              <div className="text-xl font-semibold">透明工作台已就绪</div>
              <div className="text-sm leading-6 text-muted-foreground">
                左侧恢复历史会话，中间查看流程与题目流，右侧配置知识点树。底部对话式输入区会沿用当前选择继续出题。
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

