export function formatPercent(value?: number): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '--'
  const normalized = numeric > 1 ? numeric : numeric * 100
  return `${Math.round(normalized)}%`
}

export function formatScore(value?: number): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '--'
  return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(1)
}

export function chartPercent(value: number): string {
  return formatPercent(value)
}
