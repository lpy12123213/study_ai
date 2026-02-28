import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as blueprintApi from '@/api/blueprint'
import { useTaskStore } from '@/stores/useTaskStore'
import { generateId } from '@/lib/utils'
import type { Paper } from '@/types'

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

      blueprintApi.composePaperStream(
        requestWithTaskId,
        (event) => {
          const seq = Number((event as any)?.seq)
          if (Number.isFinite(seq) && seq > 0) setLastSeq(seq)

          if (event.type === 'step' && event.step) {
            const stepId = event.step.id
            if (stepId && seenStepIds.has(stepId)) {
              updateStep(newTaskId, stepId, event.step)
            } else {
              if (stepId) seenStepIds.add(stepId)
              addStep(newTaskId, event.step)
            }
          } else if (event.type === 'progress' && event.progress !== undefined) {
            setProgress(event.progress)
          } else if (event.type === 'result' && event.result) {
            endedWithResult = true
            setResult(event.result)
            queryClient.invalidateQueries({ queryKey: ['papers'] })
          } else if (event.type === 'error') {
            setError(event.error || 'Unknown error')
            failTask(newTaskId, event.error || 'Unknown error')
            setIsComposing(false)
          }
        },
        (err) => {
          setError(err.message)
          failTask(newTaskId, err.message)
          setIsComposing(false)
        },
        () => {
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
        }
      )
    },
    [startTask, addStep, updateStep, completeTask, failTask, saveCheckpoint, getCheckpoint, queryClient]
  )

  const pause = useCallback(() => {
    if (taskId) {
      pauseTask(taskId)
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
            const seq = Number((event as any)?.seq)
            if (Number.isFinite(seq) && seq > 0) setLastSeq(seq)

            if (event.type === 'step' && event.step) {
              const stepId = event.step.id
              if (stepId && seenStepIds.has(stepId)) {
                updateStep(taskId, stepId, event.step)
              } else {
                if (stepId) seenStepIds.add(stepId)
                addStep(taskId, event.step)
              }
            } else if (event.type === 'progress' && event.progress !== undefined) {
              setProgress(event.progress)
            } else if (event.type === 'result' && event.result) {
              endedWithResult = true
              setResult(event.result)
              queryClient.invalidateQueries({ queryKey: ['papers'] })
            } else if (event.type === 'error') {
              setError(event.error || 'Unknown error')
              failTask(taskId, event.error || 'Unknown error')
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
