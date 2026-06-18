export function verdictBadgeVariant(verdict: string): 'default' | 'secondary' | 'destructive' {
  if (verdict === '好题') return 'default'
  if (verdict === '普通题') return 'secondary'
  if (verdict === '差题') return 'destructive'
  return 'secondary'
}

export function scoreClass(score: number): string {
  if (score >= 80) return 'text-emerald-600'
  if (score >= 60) return 'text-amber-600'
  return 'text-rose-600'
}

// Radix Select reserves the empty string value for clearing the selection.
export const DIFFICULTY_ANY = '__any__'
