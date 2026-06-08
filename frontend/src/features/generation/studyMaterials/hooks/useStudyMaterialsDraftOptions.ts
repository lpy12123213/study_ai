import { useEffect, useState } from 'react'
import { useFormDraft } from '@/hooks/useFormDraft'
import { isRecord, readNumber, readString } from '@/lib/record'
import type { TriState } from '@/features/generation/studyMaterials/types'
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
  type StudyDraft = {
    input: string
    subject: string
    preset: StudyMaterialsPreset
    requirements: string
    withQuestions: TriState
    withDiagrams: TriState
    enableExtraTools: TriState
    maxPoints: string
  }

  const toTriStateOrDefault = (value: unknown): TriState => {
    return value === 'on' || value === 'off' ? value : 'default'
  }

  const { clearDraft } = useFormDraft<StudyDraft>({
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
    shouldSave: (v) => {
      return Boolean(
        String(v.input || '').trim() ||
          String(v.subject || '').trim() ||
          String(v.requirements || '').trim() ||
          String(v.preset || '').trim(),
      )
    },
    onRestore: (raw) => {
      const data: unknown = raw
      if (!isRecord(data)) return
      setInput(readString(data, 'input'))
      setSubject(readString(data, 'subject'))
      setPreset(toStudyMaterialsPreset(data.preset))
      setRequirements(readString(data, 'requirements'))
      setWithQuestions(toTriStateOrDefault(data.withQuestions))
      setWithDiagrams(toTriStateOrDefault(data.withDiagrams))
      setEnableExtraTools(toTriStateOrDefault(data.enableExtraTools))
      setMaxPoints(readString(data, 'maxPoints'))
    },
  })

  useEffect(() => {
    if (!reuseTaskId) return
    let active = true

    const run = async () => {
      try {
        const task = await tasksApi.getTask(reuseTaskId)
        if (!active) return
        const req = task?.request
        if (!isRecord(req)) return

        // Start from a clean draft state.
        setCurrentConversation(null, 'study_materials')

        const options = isRecord(req.options) ? req.options : {}

        const presetRaw = readString(options, 'preset') || readString(req, 'preset')
        const preset = toStudyMaterialsPreset(presetRaw)
        const requirements = readString(options, 'requirements') || readString(req, 'requirements')

        setInput(readString(req, 'query').trim())
        setSubject(readString(req, 'subject').trim())
        setPreset(preset)
        setRequirements(requirements.trim())

        const withQuestionsRaw = options.with_questions ?? req.with_questions
        const withDiagramsRaw = options.with_diagrams ?? req.with_diagrams
        const enableExtraToolsRaw = options.enable_extra_tools ?? req.enable_extra_tools

        setWithQuestions(toTriState(withQuestionsRaw))
        setWithDiagrams(toTriState(withDiagramsRaw))
        setEnableExtraTools(toTriState(enableExtraToolsRaw))

        const mp = options.max_points ?? req.max_points
        if (typeof mp === 'number' && Number.isFinite(mp)) {
          setMaxPoints(String(mp))
        } else if (typeof mp === 'string' && mp.trim()) {
          const parsed = readNumber({ mp }, 'mp', NaN)
          setMaxPoints(Number.isFinite(parsed) ? String(parsed) : '')
        } else {
          setMaxPoints('')
        }
      } finally {
        if (!active) return
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

