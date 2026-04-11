import { useEffect, useState } from 'react'
import { useFormDraft } from '@/hooks/useFormDraft'
import type { TriState } from '@/features/studyMaterials/types'
import * as tasksApi from '@/api/tasks'

export type StudyMaterialsPreset = '' | 'quick' | 'standard' | 'deep' | 'research'

export function toStudyMaterialsPreset(value: unknown): StudyMaterialsPreset {
  const v = String(value ?? '').trim()
  if (v === 'quick' || v === 'standard' || v === 'deep' || v === 'research') return v
  return ''
}

function toTriState(value: unknown): TriState {
  if (value === true) return 'on'
  if (value === false) return 'off'
  return 'default'
}

export function useStudyMaterialsDraftOptions(opts: {
  userId: string
  activeConversationId: string | null
  isGenerating: boolean
  reuseTaskId: string
  searchParams: URLSearchParams
  setSearchParams: (next: URLSearchParams, options: { replace?: boolean }) => void
  setCurrentConversation: (id: string | null, type: 'study_materials') => void
}) {
  const {
    userId,
    activeConversationId,
    isGenerating,
    reuseTaskId,
    searchParams,
    setSearchParams,
    setCurrentConversation,
  } = opts

  const [input, setInput] = useState('')

  // Advanced options (optional; when unset, backend uses `.env` defaults)
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [subject, setSubject] = useState('')
  const [preset, setPreset] = useState<StudyMaterialsPreset>('')
  const [requirements, setRequirements] = useState('')
  const [withQuestions, setWithQuestions] = useState<TriState>('default')
  const [withDiagrams, setWithDiagrams] = useState<TriState>('default')
  const [enableExtraTools, setEnableExtraTools] = useState<TriState>('default')
  const [maxPoints, setMaxPoints] = useState<string>('')

  const draftKey = `draft:study-materials:v1:${userId || 'anon'}`
  const { clearDraft } = useFormDraft({
    storageKey: draftKey,
    enabled: !activeConversationId && !isGenerating,
    value: {
      input,
      subject,
      preset,
      requirements,
      withQuestions,
      withDiagrams,
      enableExtraTools,
      maxPoints,
    },
    shouldSave: (v: any) => {
      return Boolean(
        String(v?.input || '').trim() ||
          String(v?.subject || '').trim() ||
          String(v?.requirements || '').trim() ||
          String(v?.preset || '').trim(),
      )
    },
    onRestore: (data: any) => {
      setInput(String(data?.input || ''))
      setSubject(String(data?.subject || ''))
      setPreset(toStudyMaterialsPreset(data?.preset))
      setRequirements(String(data?.requirements || ''))
      setWithQuestions((data?.withQuestions as TriState) || 'default')
      setWithDiagrams((data?.withDiagrams as TriState) || 'default')
      setEnableExtraTools((data?.enableExtraTools as TriState) || 'default')
      setMaxPoints(String(data?.maxPoints || ''))
    },
  })

  useEffect(() => {
    if (!reuseTaskId) return
    let active = true

    const run = async () => {
      try {
        const task = await tasksApi.getTask(reuseTaskId)
        if (!active) return
        const req = (task as any)?.request
        if (!req || typeof req !== 'object' || Array.isArray(req)) return

        // Start from a clean draft state.
        setCurrentConversation(null, 'study_materials')

        const query = String((req as any).query || '').trim()
        const subject = String((req as any).subject || '').trim()
        const options =
          (req as any).options && typeof (req as any).options === 'object' && !Array.isArray((req as any).options)
            ? (req as any).options
            : {}

        const presetRaw = String((options as any).preset || (req as any).preset || '').trim()
        const preset = toStudyMaterialsPreset(presetRaw)
        const requirements = String((options as any).requirements || (req as any).requirements || '').trim()

        setInput(query)
        setSubject(subject)
        setPreset(preset)
        setRequirements(requirements)

        setWithQuestions(toTriState((options as any).with_questions ?? (req as any).with_questions))
        setWithDiagrams(toTriState((options as any).with_diagrams ?? (req as any).with_diagrams))
        setEnableExtraTools(toTriState((options as any).enable_extra_tools ?? (req as any).enable_extra_tools))

        const mp = (options as any).max_points ?? (req as any).max_points
        setMaxPoints(mp != null ? String(mp) : '')
      } finally {
        const next = new URLSearchParams(searchParams)
        next.delete('reuse_task')
        setSearchParams(next, { replace: true })
      }
    }

    void run()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reuseTaskId])

  return {
    input,
    setInput,
    optionsOpen,
    setOptionsOpen,
    subject,
    setSubject,
    preset,
    setPreset,
    requirements,
    setRequirements,
    withQuestions,
    setWithQuestions,
    withDiagrams,
    setWithDiagrams,
    enableExtraTools,
    setEnableExtraTools,
    maxPoints,
    setMaxPoints,
    clearDraft,
  }
}

