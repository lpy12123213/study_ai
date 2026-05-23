/**
 * Tiny type-safe helpers for reading optional fields out of `unknown` payloads
 * (task results, share content, search results, etc.). Prefer these over `as any`.
 */

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function readString(value: unknown, key: string): string {
  if (!isRecord(value)) return ''
  const v = value[key]
  return typeof v === 'string' ? v : ''
}

export function readNumber(value: unknown, key: string, fallback = 0): number {
  if (!isRecord(value)) return fallback
  const v = value[key]
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v)
    return Number.isFinite(n) ? n : fallback
  }
  return fallback
}

export function readBoolean(value: unknown, key: string): boolean {
  if (!isRecord(value)) return false
  return Boolean(value[key])
}

export function readStringArray(value: unknown, key: string): string[] {
  if (!isRecord(value)) return []
  const v = value[key]
  if (!Array.isArray(v)) return []
  return v.filter((entry): entry is string => typeof entry === 'string')
}

/**
 * Read a string from any of the provided keys, returning the first non-empty match.
 * Useful when the backend returns either snake_case or camelCase variants.
 */
export function readStringFrom(value: unknown, keys: readonly string[]): string {
  for (const key of keys) {
    const v = readString(value, key)
    if (v) return v
  }
  return ''
}

export function readNumberFrom(value: unknown, keys: readonly string[], fallback = 0): number {
  for (const key of keys) {
    const v = readNumber(value, key, NaN)
    if (Number.isFinite(v)) return v
  }
  return fallback
}
