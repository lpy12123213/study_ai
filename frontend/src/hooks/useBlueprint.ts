import { useEffect, useRef, useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as blueprintApi from '@/api/blueprint'
import { useTaskStore } from '@/stores/useTaskStore'
import { generateId } from '@/lib/utils'
import { normalizeSseEnvelope } from '@/lib/sse'
import { isRecord, readNumber, readStringFrom } from '@/lib/record'
import type { Paper, TaskStep } from '@/types'

/**
 * Pull the canonical fields out of a normalized SSE envelope's `data` payload
 * (which is `unknown` because backends send heterogeneous shapes).
 */
function readBlueprintEvent(envelopeData: unknown): {
  step: TaskStep | null
  progress: number | null
  result: Paper | null
  errorText: string
} {
  const data = isRecord(envelopeData) ? envelopeData : {}
  const rawStep = data.step
  const step = isRecord(rawStep) ? (rawStep as unknown as TaskStep) : null

  const rawProgress = data.progress
  const progress = typeof rawProgress === 'number' ? rawProgress : readNumber(data, 'progress', NaN)

  const rawResult = data.result
  const result = isRecord(rawResult) ? (rawResult as unknown as Paper) : null

  return {
    step,
    progress: Number.isFinite(progress) ? progress : null,
    result,
    errorText: readStringFrom(data, ['error', 'message']),
  }
}

export function useBlueprints() {
  return useQuery({
    queryKey: ['blueprints'],
    queryFn: blueprintApi.getBlueprints,
  })
}

export function useBlueprint(id: string | undefined) {
  return useQuery({
    queryKey: ['blueprint', id],
    queryFn: () => blueprintApi.getBlueprint(id!),
    enabled: !!id,
  })
}

export function useSaveBlueprint() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: blueprintApi.saveBlueprint,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['blueprints'] })
    },
  })
}

export function useDeleteBlueprint() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: blueprintApi.deleteBlueprint,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['blueprints'] })
    },
  })
}

export function useComposePaper() {
  const [isComposing, setIsComposing] = useState(false)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<Paper | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [lastSeq, setLastSeq] = useState(0)
  const composeAbortRef = useRef<AbortController | null>(null)

  const {
    startTask,
    addStep,
    updateStep,
    completeTask,
    failTask,
    pauseTask,
    saveCheckpoint,
    getCheckpoint,
  } = useTaskStore()

  const queryClient = useQueryClient()

  const compose = useCallback(
    (request: blueprintApi.ComposeRequest) => {
      const newTaskId = `compose-${generateId()}`
      setTaskId(newTaskId)
      setIsComposing(true)
      setProgress(0)
      setResult(null)
      setError(null)
      setLastSeq(0)

      startTask(newTaskId)

      const requestWithTaskId: blueprintApi.ComposeRequest = {
        ...request,
        taskId: newTaskId,
      }

      // Save initial checkpoint for resumability
      saveCheckpoint(newTaskId, {
        taskId: newTaskId,
        taskType: 'blueprint',
        status: 'running',
        currentStep: 0,
        totalSteps: 0,
        checkpoint: {
          completedSteps: [],
          pendingSteps: [],
          context: requestWithTaskId,
        },
        canResume: true,
      })

      const seenStepIds = new Set<string>()
      let endedWithResult = false
      composeAbortRef.current?.abort()
      const controller = new AbortController()
      composeAbortRef.current = controller

      blueprintApi.composePaperStream(
        requestWithTaskId,
        (event) => {
          const env = normalizeSseEnvelope(event)

          const seq = env.seq
          if (Number.isFinite(seq) && (seq || 0) > 0) setLastSeq(seq || 0)

          const { step, progress: progressValue, result: resultValue, errorText } = readBlueprintEvent(env.data)

          if (controller.signal.aborted) return
          if (env.type === 'step' && step) {
            const stepId = step.id
            if (stepId && seenStepIds.has(stepId)) {
              updateStep(newTaskId, stepId, step)
            } else {
              if (stepId) seenStepIds.add(stepId)
              addStep(newTaskId, step)
            }
          } else if (env.type === 'progress' && progressValue !== null) {
            setProgress(progressValue)
          } else if (env.type === 'result' && resultValue) {
            endedWithResult = true
            setResult(resultValue)
            queryClient.invalidateQueries({ queryKey: ['papers'] })
          } else if (env.type === 'error') {
            const msg = errorText || 'Unknown error'
            setError(msg)
            failTask(newTaskId, msg)
            setIsComposing(false)
          }
        },
        (err) => {
          if (controller.signal.aborted) return
          setError(err.message)
          failTask(newTaskId, err.message)
          setIsComposing(false)
        },
        () => {
          if (controller.signal.aborted) return
          setIsComposing(false)
          setProgress((p) => (p >= 99 ? 100 : p))

          if (endedWithResult) {
            completeTask(newTaskId)
            return
          }

          const cp = getCheckpoint(newTaskId)
          if (cp?.status === 'paused') return
          // Stream ended without a result: treat as failure so the user can retry/resume.
          failTask(newTaskId, 'Task ended unexpectedly')
        },
        { signal: controller.signal }
      )
    },
    [startTask, addStep, updateStep, completeTask, failTask, saveCheckpoint, getCheckpoint, queryClient]
  )

  const pause = useCallback(() => {
    if (taskId) {
      pauseTask(taskId)
      composeAbortRef.current?.abort()
      blueprintApi.pauseComposeTask(taskId).catch(console.error)
      setIsComposing(false)
    }
  }, [taskId, pauseTask])

  const resume = useCallback(async () => {
    if (taskId) {
      const checkpoint = getCheckpoint(taskId)
      if (checkpoint) {
        setIsComposing(true)
        setError(null)
        await blueprintApi.resumeComposeTask(taskId)

        const seenStepIds = new Set<string>()
        for (const s of useTaskStore.getState().getTaskSteps(taskId)) {
          if (s?.id) seenStepIds.add(s.id)
        }
        let endedWithResult = false

        blueprintApi.streamComposeTask(
          taskId,
          lastSeq,
          (event) => {
            const env = normalizeSseEnvelope(event)

            const seq = env.seq
            if (Number.isFinite(seq) && (seq || 0) > 0) setLastSeq(seq || 0)

            const { step, progress: progressValue, result: resultValue, errorText } = readBlueprintEvent(env.data)

            if (env.type === 'step' && step) {
              const stepId = step.id
              if (stepId && seenStepIds.has(stepId)) {
                updateStep(taskId, stepId, step)
              } else {
                if (stepId) seenStepIds.add(stepId)
                addStep(taskId, step)
              }
            } else if (env.type === 'progress' && progressValue !== null) {
              setProgress(progressValue)
            } else if (env.type === 'result' && resultValue) {
              endedWithResult = true
              setResult(resultValue)
              queryClient.invalidateQueries({ queryKey: ['papers'] })
            } else if (env.type === 'error') {
              const msg = errorText || 'Unknown error'
              setError(msg)
              failTask(taskId, msg)
              setIsComposing(false)
            }
          },
          (err) => {
            setError(err.message)
            failTask(taskId, err.message)
            setIsComposing(false)
          },
          () => {
            setIsComposing(false)
            setProgress((p) => (p >= 99 ? 100 : p))
            if (endedWithResult) completeTask(taskId)
          }
        )
      }
    }
  }, [taskId, getCheckpoint, lastSeq, addStep, updateStep, completeTask, failTask, queryClient])

  useEffect(() => {
    return () => {
      composeAbortRef.current?.abort()
    }
  }, [])

  return {
    compose,
    pause,
    resume,
    isComposing,
    progress,
    result,
    error,
    taskId,
  }
}
