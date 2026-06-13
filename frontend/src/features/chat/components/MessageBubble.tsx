
import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { BrandMark } from '@/components/shared/BrandMark'
import { Markdown } from '@/components/shared/Markdown'
import { APP_ASSISTANT_NAME } from '@/constants/branding'
import type { Message } from '@/types'

export function MessageBubble({ message, disableMotion }: { message: Message; disableMotion: boolean }) {
  const isUser = message.role === 'user'
  const [showSteps, setShowSteps] = useState(false)

  if (isUser) {
    if (disableMotion) {
      return (
        <div className="flex justify-end mb-6">
          <div className="aurora-chat-user max-w-[85%] sm:max-w-[75%] px-5 py-3 text-sm leading-6 text-foreground">
            <div className="whitespace-pre-wrap">{message.content}</div>
          </div>
        </div>
      )
    }
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex justify-end mb-6"
      >
        <div className="aurora-chat-user max-w-[85%] sm:max-w-[75%] px-5 py-3 text-sm leading-6 text-foreground">
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>
      </motion.div>
    )
  }

  if (disableMotion) {
    return (
      <div className="aurora-chat-assistant flex flex-col gap-2 mb-8 max-w-3xl w-full">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
          <div className="aurora-chat-mark h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center">
            <BrandMark size={12} />
          </div>
          <span>{APP_ASSISTANT_NAME}</span>
        </div>

        <Markdown content={message.content} className="text-foreground leading-7" />

        {message.steps && message.steps.length > 0 && (
          <div className="mt-3">
            <Button
              variant="outline"
              size="sm"
              className="aurora-chat-steps-button h-8 text-xs font-normal gap-1.5"
              onClick={() => setShowSteps(!showSteps)}
            >
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              {showSteps ? '隐藏' : '查看'} {message.steps.length} 个思考步骤
              {showSteps ? <ChevronUp className="h-3 w-3 opacity-50" /> : <ChevronDown className="h-3 w-3 opacity-50" />}
            </Button>

            {showSteps && (
              <div className="aurora-chat-steps-panel mt-3 overflow-hidden rounded-lg" data-state="success">
                <div className="p-4">
                  <TaskTimeline steps={message.steps} />
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="aurora-chat-assistant flex flex-col gap-2 mb-8 max-w-3xl w-full"
    >
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
        <div className="aurora-chat-mark h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center">
          <BrandMark size={12} />
        </div>
        <span>{APP_ASSISTANT_NAME}</span>
      </div>
      
      <Markdown content={message.content} className="text-foreground leading-7" />

      {message.steps && message.steps.length > 0 && (
        <div className="mt-3">
          <Button
            variant="outline"
            size="sm"
            className="aurora-chat-steps-button h-8 text-xs font-normal gap-1.5"
            onClick={() => setShowSteps(!showSteps)}
          >
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            {showSteps ? '隐藏' : '查看'} {message.steps.length} 个思考步骤
            {showSteps ? <ChevronUp className="h-3 w-3 opacity-50" /> : <ChevronDown className="h-3 w-3 opacity-50" />}
          </Button>

          <AnimatePresence>
            {showSteps && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="aurora-chat-steps-panel mt-3 overflow-hidden rounded-lg"
                data-state="success"
              >
                <div className="p-4">
                   <TaskTimeline steps={message.steps} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  )
}
