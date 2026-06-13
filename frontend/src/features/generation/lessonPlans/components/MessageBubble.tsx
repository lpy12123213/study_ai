import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react'
import { Markdown } from '@/components/shared/Markdown'
import { BrandMark } from '@/components/shared/BrandMark'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { Button } from '@/components/ui/button'
import { APP_ASSISTANT_NAME } from '@/constants/branding'
import type { Message } from '@/types'
import { LessonPlanAttachment } from '@/features/generation/lessonPlans/components/LessonPlanAttachment'

export function MessageBubble({ message, disableMotion = false }: { message: Message; disableMotion?: boolean }) {
  const isUser = message.role === 'user'
  const [showSteps, setShowSteps] = useState(false)
  const userBubbleClass =
    'aurora-lesson-user-bubble max-w-[85%] sm:max-w-[75%] rounded-2xl px-5 py-3 text-sm leading-6 text-foreground'
  const assistantWrapClass = 'aurora-lesson-assistant flex flex-col gap-2 mb-8 w-full'
  const assistantMarkClass = 'aurora-lesson-mark h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center'

  if (isUser) {
    if (disableMotion) {
      return (
        <div className="flex justify-end mb-6">
          <div className={userBubbleClass}>
            <div className="whitespace-pre-wrap">{message.content}</div>
          </div>
        </div>
      )
    }
    return (
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end mb-6">
        <div className={userBubbleClass}>
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>
      </motion.div>
    )
  }

  const assistantBody = (
    <>
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
        <div className={assistantMarkClass}>
          <BrandMark size={12} />
        </div>
        <span>{APP_ASSISTANT_NAME}</span>
      </div>

      <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-7">
        <Markdown markdown={message.content} />
      </div>

      {message.attachment?.type === 'lesson_plan' && <LessonPlanAttachment lessonPlanId={message.attachment.lessonPlanId} />}

      {message.steps && message.steps.length > 0 && (
        <div className="mt-3">
          <Button
            variant="outline"
            size="sm"
            className="aurora-lesson-steps-button h-8 text-xs font-normal gap-1.5"
            onClick={() => setShowSteps(!showSteps)}
          >
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            {showSteps ? '隐藏' : '查看'} {message.steps.length} 个思考步骤
            {showSteps ? (
              <ChevronUp className="h-3 w-3 opacity-50" />
            ) : (
              <ChevronDown className="h-3 w-3 opacity-50" />
            )}
          </Button>

          <AnimatePresence>
            {showSteps && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="aurora-lesson-steps-panel mt-3 overflow-hidden rounded-lg"
              >
                <div className="p-4">
                  <TaskTimeline steps={message.steps} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </>
  )

  if (disableMotion) {
    return <div className={assistantWrapClass}>{assistantBody}</div>
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={assistantWrapClass}
    >
      {assistantBody}
    </motion.div>
  )
}

