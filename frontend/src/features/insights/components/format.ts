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

export const insightTooltipContentStyle = {
  background: 'rgba(5, 7, 10, 0.92)',
  border: '1px solid var(--border-default-color)',
  borderRadius: '12px',
  boxShadow: 'var(--shadow-elevation-high)',
  color: 'var(--text-primary)',
} as const

export const insightTooltipLabelStyle = {
  color: 'var(--text-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: '12px',
} as const

export const insightAxisTick = {
  fill: 'var(--text-secondary)',
  fontSize: 12,
} as const
