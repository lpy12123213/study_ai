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

  const {
    startTask,
    addStep,
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

      startTask(newTaskId)

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
          context: request,
        },
        canResume: true,
      })

      blueprintApi.composePaperStream(
        request,
        (event) => {
          if (event.type === 'step' && event.step) {
            addStep(newTaskId, event.step)
          } else if (event.type === 'progress' && event.progress !== undefined) {
            setProgress(event.progress)
          } else if (event.type === 'result' && event.result) {
            setResult(event.result)
            queryClient.invalidateQueries({ queryKey: ['papers'] })
          } else if (event.type === 'error') {
            setError(event.error || 'Unknown error')
            failTask(newTaskId, event.error || 'Unknown error')
          }
        },
        (err) => {
          setError(err.message)
          failTask(newTaskId, err.message)
          setIsComposing(false)
        },
        () => {
          completeTask(newTaskId)
          setIsComposing(false)
        }
      )
    },
    [startTask, addStep, completeTask, failTask, saveCheckpoint, queryClient]
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
        await blueprintApi.resumeComposeTask(taskId)
        // Re-subscribe to the stream
        // This would need backend support for resumable tasks
      }
    }
  }, [taskId, getCheckpoint])

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
