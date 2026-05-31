type KeyboardSubmitEvent = {
  key: string
  shiftKey?: boolean
  isComposing?: boolean
  keyCode?: number
  nativeEvent?: {
    isComposing?: boolean
    keyCode?: number
  }
}

export function isImeCompositionKeyboardEvent(event: KeyboardSubmitEvent): boolean {
  return Boolean(
    event.isComposing ||
      event.nativeEvent?.isComposing ||
      event.keyCode === 229 ||
      event.nativeEvent?.keyCode === 229,
  )
}

export function shouldSubmitOnEnter(event: KeyboardSubmitEvent): boolean {
  return event.key === 'Enter' && !event.shiftKey && !isImeCompositionKeyboardEvent(event)
}
