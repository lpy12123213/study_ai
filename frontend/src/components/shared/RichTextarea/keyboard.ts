import { isImeCompositionKeyboardEvent } from '@/lib/keyboard'

type RichTextareaKeyboardEvent = {
  key: string
  shiftKey?: boolean
  isComposing?: boolean
  keyCode?: number
  nativeEvent?: {
    isComposing?: boolean
    keyCode?: number
  }
}

export type RichTextareaKeyboardOptions = {
  submitOnEnter?: boolean
  viewComposing?: boolean
}

export function shouldSubmitRichTextareaEvent(
  event: RichTextareaKeyboardEvent,
  options: RichTextareaKeyboardOptions = {},
): boolean {
  if (options.submitOnEnter === false) return false
  if (options.viewComposing) return false
  return event.key === 'Enter' && !event.shiftKey && !isImeCompositionKeyboardEvent(event)
}
