import type { TaskStep } from '@/types'
import { isRecord, readNumber, readString } from '@/lib/record'

export type SlotShortfall = {
  slotIndex: number
  questionType: string
  difficulty: string
  requested: number
  selected: number
}

const PAPER_BALANCE_STEP_ID = 'paper_balance'

/**
 * Extract `slotShortfalls` from the `paper_balance` step output produced by the
 * compose runner. The output shape is intentionally permissive so we read with
 * narrowing helpers rather than `as any`.
 */
export function extractSlotShortfalls(steps: readonly (TaskStep | undefined | null)[]): SlotShortfall[] {
  const step = (steps || []).find((s) => s?.id === PAPER_BALANCE_STEP_ID)
  const output = step?.output
  const list = isRecord(output) && Array.isArray(output.slotShortfalls) ? output.slotShortfalls : []

  const out: SlotShortfall[] = []
  for (const entry of list) {
    if (!isRecord(entry)) continue
    const slotIndex = readNumber(entry, 'slotIndex', NaN)
    if (!Number.isFinite(slotIndex)) continue
    const requested = readNumber(entry, 'requested', 0)
    const selected = readNumber(entry, 'selected', 0)
    if (requested <= selected) continue
    out.push({
      slotIndex,
      questionType: readString(entry, 'questionType'),
      difficulty: readString(entry, 'difficulty'),
      requested,
      selected,
    })
  }
  return out
}
