/**
 * Parse a comma/whitespace separated string of tags into a unique, trimmed list,
 * capped at 20 entries to match backend constraints.
 *
 * Mirrors the legacy parser from `historySidebar/utils.ts` so the shared dialog
 * stays drop-in compatible with HistorySidebar.
 */
export function parseTagsInput(raw: string): string[] {
  const tags = raw
    .split(/[,，\n]/)
    .map((tag) => tag.trim())
    .filter(Boolean)
    .slice(0, 20)

  return Array.from(new Set(tags))
}
