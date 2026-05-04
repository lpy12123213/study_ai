
import { motion } from 'framer-motion'
import { Badge } from '@/components/ui/badge'
import type { DeepThinkChatMessage } from '@/features/deepThink/types'

export function DeepThinkUserBubble({ message }: { message: DeepThinkChatMessage }) {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end mb-6">
      <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl bg-muted px-5 py-3 text-sm leading-6 text-foreground">
        <div className="whitespace-pre-wrap">{message.content}</div>
        {(message.meta?.subject || message.meta?.imageUrl) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {message.meta?.subject && (
              <Badge variant="secondary" className="text-[11px] font-normal">
                学科：{message.meta.subject}
              </Badge>
            )}
            {message.meta?.imageUrl && (
              <Badge variant="outline" className="text-[11px] font-normal">
                已附题图
              </Badge>
            )}
          </div>
        )}
      </div>
    </motion.div>
  )
}
