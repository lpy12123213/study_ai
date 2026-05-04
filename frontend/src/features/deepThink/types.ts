
import type { Message } from '@/types'

export type DeepThinkChatMessage = Message & {
  meta?: {
    subject?: string
    imageUrl?: string
  }
}
