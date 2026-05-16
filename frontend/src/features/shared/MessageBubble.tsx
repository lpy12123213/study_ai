import { type ReactNode, useCallback, useState } from 'react'
import { motion } from 'framer-motion'
import { Check, Copy, RefreshCw } from 'lucide-react'
import { Markdown } from '@/components/shared/Markdown'
import { BrandMark } from '@/components/shared/BrandMark'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { APP_ASSISTANT_NAME } from '@/constants/branding'
import { LessonPlanAttachment } from '@/features/lessonPlans/components/LessonPlanAttachment'
import { ToolUseLogPanel } from '@/features/shared/ToolUseLogPanel'
import { extractStepKnowledgePoints } from '@/features/studyMaterials/utils'
import { cn } from '@/lib/utils'
import type { Message, TaskStep } from '@/types'

type MessageBubbleVariant = 'chat' | 'lessonPlan' | 'studyMaterials'

type MessageBubbleProps = {
  message: Message
  disableMotion?: boolean
  variant?: MessageBubbleVariant
  /** Whether this message is currently being streamed */
  isStreaming?: boolean
  /** Callback to regenerate this message */
  onRegenerate?: () => void
}

function MotionWrapper({
  children,
  className,
  disableMotion,
}: {
  children: ReactNode
  className: string
  disableMotion: boolean
}) {
  if (disableMotion) {
    return <div className={className}>{children}</div>
  }
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }} className={className}>
      {children}
    </motion.div>
  )
}

function UserMessage({ content, disableMotion }: { content: string; disableMotion: boolean }) {
  return (
    <MotionWrapper disableMotion={disableMotion} className="flex justify-end mb-8">
      <div className="max-w-[85%] sm:max-w-[70%] rounded-[24px] bg-muted/60 px-5 py-3 text-[15px] leading-relaxed text-foreground font-normal">
        <div className="whitespace-pre-wrap">{content}</div>
      </div>
    </MotionWrapper>
  )
}

function AssistantContent({ message, variant, isStreaming }: { message: Message; variant: MessageBubbleVariant; isStreaming?: boolean }) {
  return <Markdown markdown={message.content} streaming={isStreaming} />
}

function filterGlobalSteps(steps: TaskStep[]): TaskStep[] {
  return steps.filter((step) => extractStepKnowledgePoints(step).length !== 1)
}

function StudyMaterialSteps({ steps }: { steps: TaskStep[] }) {
  const globalSteps = filterGlobalSteps(steps)
  if (globalSteps.length === 0) return null

  return (
    <div className="mt-4 overflow-hidden rounded-xl border border-border/40 bg-transparent">
      <div className="px-5 py-3 text-xs font-medium text-muted-foreground flex items-center justify-between border-b border-border/40 bg-muted/20">
        <span>Process Log</span>
        <span className="tabular-nums text-foreground">{globalSteps.length} steps</span>
      </div>
      <div className="p-5">
        <TaskTimeline steps={globalSteps} />
      </div>
    </div>
  )
}

function MessageActions({ content, onRegenerate }: { content: string; onRegenerate?: () => void }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // ignore
    }
  }, [content])

  if (!content) return null

  return (
    <div className="flex items-center gap-1 mt-2 opacity-0 group-hover/msg:opacity-100 transition-opacity">
      <button
        type="button"
        onClick={handleCopy}
        className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        aria-label="复制消息"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      {onRegenerate && (
        <button
          type="button"
          onClick={onRegenerate}
          className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          aria-label="重新生成"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}

export function MessageBubble({ message, disableMotion = false, variant = 'chat', isStreaming = false, onRegenerate }: MessageBubbleProps) {
  if (message.role === 'user') {
    return <UserMessage content={message.content} disableMotion={disableMotion} />
  }

  const steps = message.steps || []
  const widthClass = variant === 'lessonPlan' ? 'w-full' : 'max-w-3xl w-full'

  return (
    <MotionWrapper disableMotion={disableMotion} className={cn('group/msg flex flex-col gap-2 mb-10', widthClass)}>
      <div className="flex items-center gap-3 text-sm font-medium text-foreground mb-3 select-none">
        <BrandMark size={16} />
        <span>{APP_ASSISTANT_NAME}</span>
      </div>

      <div className="prose prose-base dark:prose-invert max-w-none text-foreground/90 leading-8 pl-7">
        <AssistantContent message={message} variant={variant} isStreaming={isStreaming} />
      </div>

      {variant === 'lessonPlan' && message.attachment?.type === 'lesson_plan' && (
        <div className="pl-7 mt-4">
          <LessonPlanAttachment lessonPlanId={message.attachment.lessonPlanId} />
        </div>
      )}

      {variant === 'studyMaterials' ? (
        <div className="pl-7">
          <StudyMaterialSteps steps={steps} />
        </div>
      ) : (
        <div className="pl-7 mt-2">
          <ToolUseLogPanel steps={steps} disableMotion={disableMotion} />
        </div>
      )}

      {/* Message actions: copy, regenerate (only when not streaming) */}
      {!isStreaming && message.content && (
        <div className="pl-7">
          <MessageActions content={message.content} onRegenerate={onRegenerate} />
        </div>
      )}
    </MotionWrapper>
  )
}
