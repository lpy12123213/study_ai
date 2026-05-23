import { useCallback, useEffect, useRef, useState } from 'react'
import { generateFullPaperStream, type GenerateFullPaperStreamEvent } from '@/api/papers'
import { generateId } from '@/lib/utils'
import { isRecord, readNumber, readString, readStringFrom } from '@/lib/record'
import type { TaskStep } from '@/types'

export type OneClickPaperResult = {
  paperId: number
  paperName: string
  questionCount: number
}

export type OneClickPaperRequest = {
  subject: string
  topic?: string
  paperName?: string
  totalPoints: number
  timeLimit: number
  hardPct: number
  useStudyArchive: boolean
}

export type OneClickPaperState = {
  taskId: string
  progress: number
  steps: TaskStep[]
  error: string
  result: OneClickPaperResult | null
  isGenerating: boolean
}

const DEFAULTS = { totalPoints: 150, timeLimit: 120 }

function clampDistribution(hardPct: number) {
  const hard = Math.max(0, Math.min(0.6, Number(hardPct || 0) / 100))
  const easy = (1 - hard) * 0.4
  const medium = Math.max(0, 1 - hard - easy)
  return {
    easy: Number(easy.toFixed(2)),
    medium: Number(medium.toFixed(2)),
    hard: Number(hard.toFixed(2)),
  }
}

function asTaskStep(value: unknown): TaskStep | null {
  if (!isRecord(value)) return null
  const id = readString(value, 'id')
  const title = readString(value, 'title')
  const status = readString(value, 'status')
  if (!id || !title || !status) return null
  return value as unknown as TaskStep
}

export function useOneClickPaper() {
  const abortRef = useRef<AbortController | null>(null)

  const [taskId, setTaskId] = useState('')
  const [progress, setProgress] = useState(0)
  const [steps, setSteps] = useState<TaskStep[]>([])
  const [error, setError] = useState('')
  const [result, setResult] = useState<OneClickPaperResult | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)

  const upsertStep = useCallback((incoming: TaskStep) => {
    setSteps((prev) => {
      const idx = prev.findIndex((s) => s.id === incoming.id)
      if (idx >= 0) {
        const next = [...prev]
        next[idx] = { ...next[idx], ...incoming }
        return next
      }
      return [...prev, incoming]
    })
  }, [])

  const reset = useCallback(() => {
    setTaskId('')
    setProgress(0)
    setSteps([])
    setError('')
    setResult(null)
  }, [])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsGenerating(false)
  }, [])

  const generate = useCallback(
    (request: OneClickPaperRequest) => {
      if (!request.subject) return

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      const localTaskId = generateId().slice(0, 12)
      setTaskId(localTaskId)
      setError('')
      setResult(null)
      setSteps([])
      setProgress(0)
      setIsGenerating(true)

      const safeTotalPoints = Math.max(30, Math.min(Number(request.totalPoints || DEFAULTS.totalPoints), 300))
      const safeTimeLimit = Math.max(30, Math.min(Number(request.timeLimit || DEFAULTS.timeLimit), 240))

      generateFullPaperStream(
        {
          taskId: localTaskId,
          subject: request.subject,
          topic: request.topic?.trim() || undefined,
          paperName: request.paperName?.trim() || undefined,
          totalPoints: safeTotalPoints,
          timeLimit: safeTimeLimit,
          difficultyDistribution: clampDistribution(request.hardPct),
          useStudyArchive: Boolean(request.useStudyArchive),
        },
        (evt: GenerateFullPaperStreamEvent) => {
          const kind = String(evt?.type || '').trim()

          if (kind === 'progress') {
            const p = readNumber(evt, 'progress', NaN)
            if (Number.isFinite(p)) setProgress(p)
            return
          }

          if (kind === 'step') {
            const step = asTaskStep(evt?.step)
            if (step) upsertStep(step)
            return
          }

          if (kind === 'result') {
            const resultPayload = evt?.result
            const paperId = readNumber(resultPayload, 'paper_id', NaN)
            if (Number.isFinite(paperId)) {
              setResult({
                paperId,
                paperName: readString(resultPayload, 'paper_name') || `试卷-${paperId}`,
                questionCount: readNumber(resultPayload, 'question_count', 0),
              })
            }
            setProgress(100)
            setIsGenerating(false)
            return
          }

          if (kind === 'error') {
            const message =
              readStringFrom(evt, ['error', 'message']) ||
              readStringFrom(evt?.data, ['error', 'message']) ||
              'generate_full_failed'
            setError(message)
            setIsGenerating(false)
          }
        },
        (err) => {
          setError(err?.message || 'generate_full_failed')
          setIsGenerating(false)
        },
        () => {
          setIsGenerating(false)
        },
        { signal: controller.signal },
      )
    },
    [upsertStep],
  )

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  return { taskId, progress, steps, error, result, isGenerating, generate, stop, reset }
}
