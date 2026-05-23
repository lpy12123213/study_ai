import { useEffect } from 'react'
import { useFormDraft } from '@/hooks/useFormDraft'
import { generateId } from '@/lib/utils'
import { isRecord, readNumber, readString } from '@/lib/record'
import * as tasksApi from '@/api/tasks'
import type { BlueprintSlot } from '@/types'

export type BlueprintMode = 'blueprint' | 'one_click'

export type BlueprintDraft = {
  mode: BlueprintMode
  subject: string
  topic: string
  slots: BlueprintSlot[]
  blueprintName: string
  gradeId: string
  textbookVersionId: string
  oneClickTotalPoints: number
  oneClickTimeLimit: number
  oneClickHardPct: number
  oneClickUseArchive: boolean
}

export type BlueprintDraftSetters = {
  setMode: (next: BlueprintMode) => void
  setSubject: (next: string) => void
  setTopic: (next: string) => void
  setSlots: (next: BlueprintSlot[]) => void
  setBlueprintName: (next: string) => void
  setGradeId: (next: string) => void
  setTextbookVersionId: (next: string) => void
  setOneClickTotalPoints: (next: number) => void
  setOneClickTimeLimit: (next: number) => void
  setOneClickHardPct: (next: number) => void
  setOneClickUseArchive: (next: boolean) => void
}

function normalizeSlot(value: unknown): BlueprintSlot | null {
  if (!isRecord(value)) return null
  const questionType = readString(value, 'questionType') || readString(value, 'question_type')
  if (!questionType) return null
  return {
    id: readString(value, 'id') || generateId(),
    questionType,
    count: readNumber(value, 'count', 1),
    score: readNumber(value, 'score', 0),
    difficulty: readString(value, 'difficulty') || 'medium',
  }
}

function normalizeSlotList(value: unknown): BlueprintSlot[] {
  if (!Array.isArray(value)) return []
  const out: BlueprintSlot[] = []
  for (const entry of value) {
    const slot = normalizeSlot(entry)
    if (slot) out.push(slot)
  }
  return out
}

/**
 * Draft persistence for the blueprint configuration form. Restores the last
 * unsubmitted draft on mount and clears it whenever a paper has been produced.
 */
export function useBlueprintDraft({
  userId,
  enabled,
  value,
  setters,
  hasResult,
}: {
  userId: string
  enabled: boolean
  value: BlueprintDraft
  setters: BlueprintDraftSetters
  hasResult: boolean
}) {
  const draftKey = `draft:blueprint:v1:${userId || 'anon'}`

  const { clearDraft } = useFormDraft<BlueprintDraft>({
    storageKey: draftKey,
    enabled,
    value,
    shouldSave: (v) => {
      const subject = String(v.subject || '').trim()
      const topic = String(v.topic || '').trim()
      const anySlot = Array.isArray(v.slots) && v.slots.length > 0
      return Boolean(subject || topic || anySlot)
    },
    onRestore: (raw) => {
      const data: unknown = raw
      if (!isRecord(data)) return
      const mode = readString(data, 'mode')
      setters.setMode(mode === 'one_click' ? 'one_click' : 'blueprint')
      setters.setSubject(readString(data, 'subject'))
      setters.setTopic(readString(data, 'topic'))
      setters.setBlueprintName(readString(data, 'blueprintName'))
      setters.setGradeId(readString(data, 'gradeId'))
      setters.setTextbookVersionId(readString(data, 'textbookVersionId'))
      setters.setOneClickTotalPoints(readNumber(data, 'oneClickTotalPoints', 150))
      setters.setOneClickTimeLimit(readNumber(data, 'oneClickTimeLimit', 120))
      setters.setOneClickHardPct(readNumber(data, 'oneClickHardPct', 20))
      const useArchiveRaw = data.oneClickUseArchive
      setters.setOneClickUseArchive(useArchiveRaw === undefined ? true : Boolean(useArchiveRaw))
      setters.setSlots(normalizeSlotList(data.slots))
    },
  })

  useEffect(() => {
    if (!hasResult) return
    clearDraft()
  }, [clearDraft, hasResult])

  return { clearDraft }
}

/**
 * Restore a previous blueprint configuration from a unified task ID
 * (e.g. the user picked "reuse this task" from the task center).
 */
export function useReuseTaskHydration({
  reuseTaskId,
  enabled,
  setters,
  onConsumed,
}: {
  reuseTaskId: string
  enabled: boolean
  setters: BlueprintDraftSetters
  onConsumed: () => void
}) {
  useEffect(() => {
    if (!enabled || !reuseTaskId) return

    let active = true
    const run = async () => {
      try {
        const task = await tasksApi.getTask(reuseTaskId)
        if (!active) return
        const req = task?.request
        if (!isRecord(req)) return

        setters.setSubject(readString(req, 'subject'))
        setters.setTopic(readString(req, 'topic'))
        setters.setBlueprintName(readString(req, 'paperName') || readString(req, 'paper_name'))

        const filters = isRecord(req.filters) ? req.filters : {}
        const gradeId = filters.gradeId ?? filters.grade_id
        const textbookVersion = filters.textbookVersion ?? filters.textbook_version
        setters.setGradeId(gradeId != null ? String(gradeId) : '')
        setters.setTextbookVersionId(textbookVersion != null ? String(textbookVersion) : '')

        const slots = normalizeSlotList(req.slots).map((slot) => ({ ...slot, id: generateId() }))
        setters.setSlots(slots)
      } finally {
        if (active) onConsumed()
      }
    }
    void run()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, reuseTaskId])
}
