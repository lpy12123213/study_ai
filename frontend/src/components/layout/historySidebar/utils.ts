import {
  BookOpen,
  BookOpenCheck,
  LayoutTemplate,
  MessagesSquare,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ConversationItem, ConversationType } from '@/types'
// Re-export the canonical implementation so historySidebar callers do not
// drift from the shared TagEditDialog parser.
export { parseTagsInput } from '@/components/shared/TagEditDialog'

export const typeIcons: Record<ConversationType, LucideIcon> = {
  chat: MessagesSquare,
  blueprint: LayoutTemplate,
  lesson_plan: BookOpenCheck,
  study_materials: BookOpen,
}

export function metaKey(itemType: string, itemId: string): string {
  return `${String(itemType)}:${String(itemId)}`
}

export function getPageTypeFilter(pathname: string): ConversationType | null {
  if (pathname.startsWith('/study-materials')) return 'study_materials'
  if (pathname.startsWith('/lesson-plans')) return 'lesson_plan'
  if (pathname.startsWith('/chat')) return 'chat'
  if (pathname.startsWith('/blueprint')) return 'blueprint'
  return null
}

export function conversationTarget(item: ConversationItem): string {
  if (item.type === 'chat') return `/chat/${item.id}`
  if (item.type === 'blueprint') return '/blueprint'
  if (item.type === 'lesson_plan') return '/lesson-plans'
  return '/study-materials'
}

export function newConversationTarget(pathname: string): string {
  if (pathname.startsWith('/study-materials')) return '/study-materials'
  if (pathname.startsWith('/lesson-plans')) return '/lesson-plans'
  if (pathname.startsWith('/blueprint')) return '/blueprint'
  return '/chat'
}
