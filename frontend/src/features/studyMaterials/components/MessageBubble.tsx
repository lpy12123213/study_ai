import { motion } from 'framer-motion'
import { BrandMark } from '@/components/shared/BrandMark'
import { SecureMarkdown } from '@/components/shared/SecureMarkdown'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { extractStepKnowledgePoints } from '@/features/studyMaterials/utils'
import type { Message, TaskStep } from '@/types'

export function MessageBubble({ message, disableMotion }: { message: Message; disableMotion: boolean }) {
  const isUser = message.role === 'user'

  if (isUser) {
    if (disableMotion) {
      return (
        <div className="flex justify-end mb-6">
          <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl bg-muted px-5 py-3 text-sm leading-6 text-foreground">
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
        <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl bg-muted px-5 py-3 text-sm leading-6 text-foreground">
          <div className="whitespace-pre-wrap">{message.content}</div>
        </div>
      </motion.div>
    )
  }

  if (disableMotion) {
    return (
      <div className="flex flex-col gap-2 mb-8 max-w-3xl w-full">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
          <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center">
            <BrandMark size={12} />
          </div>
          <span>学习助手</span>
        </div>

        <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-7">
          <SecureMarkdown markdown={message.content} />
        </div>

        {message.steps && message.steps.length > 0 && (
          (() => {
            const allSteps = message.steps || []
            const globalSteps: TaskStep[] = []
            for (const step of allSteps) {
              const kps = extractStepKnowledgePoints(step)
              if (kps.length !== 1) {
                globalSteps.push(step)
              }
            }
            if (globalSteps.length === 0) return null

            return (
              <div className="mt-3 overflow-hidden rounded-lg border border-border bg-card">
                <div className="px-4 py-2 text-xs text-muted-foreground flex items-center justify-between">
                  <span>主流程步骤</span>
                  <span className="tabular-nums">{globalSteps.length} 步</span>
                </div>
                <div className="p-4 bg-muted/30">
                  <TaskTimeline steps={globalSteps} />
                </div>
              </div>
            )
          })()
        )}
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-2 mb-8 max-w-3xl w-full"
    >
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
        <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center">
          <BrandMark size={12} />
        </div>
        <span>学习助手</span>
      </div>

      <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-7">
        <SecureMarkdown markdown={message.content} />
      </div>

      {message.steps && message.steps.length > 0 && (
        (() => {
          const allSteps = message.steps || []

          // Only show global steps (main agent), subagent steps are shown in the right panel
          const globalSteps: TaskStep[] = []

          for (const step of allSteps) {
            const kps = extractStepKnowledgePoints(step)
            // Steps without a specific knowledge point are global (main agent)
            if (kps.length !== 1) {
              globalSteps.push(step)
            }
          }

          if (globalSteps.length === 0) return null

          return (
            <div className="mt-3 overflow-hidden rounded-lg border border-border bg-card">
              <div className="px-4 py-2 text-xs text-muted-foreground flex items-center justify-between">
                <span>主流程步骤</span>
                <span className="tabular-nums">{globalSteps.length} 步</span>
              </div>
              <div className="p-4 bg-muted/30">
                <TaskTimeline steps={globalSteps} />
              </div>
            </div>
          )
        })()
      )}
    </motion.div>
  )
}
