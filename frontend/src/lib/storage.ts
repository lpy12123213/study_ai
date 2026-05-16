const pendingWrites = new Map<string, number>()

function canUseWindowStorage(): boolean {
  return typeof window !== 'undefined' && Boolean(window.localStorage)
}

export function setLocalStorageThrottled(key: string, value: string, delayMs = 200): void {
  if (!canUseWindowStorage()) return
  const normalizedDelay = Math.max(0, Math.floor(Number(delayMs) || 0))
  const existing = pendingWrites.get(key)
  if (existing) {
    window.clearTimeout(existing)
  }

  const write = () => {
    pendingWrites.delete(key)
    window.localStorage.setItem(key, value)
  }

  if (normalizedDelay === 0) {
    write()
    return
  }

  pendingWrites.set(key, window.setTimeout(write, normalizedDelay))
}

export function removeLocalStorageNow(key: string): void {
  if (!canUseWindowStorage()) return
  const existing = pendingWrites.get(key)
  if (existing) {
    window.clearTimeout(existing)
    pendingWrites.delete(key)
  }
  window.localStorage.removeItem(key)
}
