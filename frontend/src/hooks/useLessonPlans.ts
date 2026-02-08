import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as lessonPlansApi from '@/api/lessonPlans'
import { useTaskStore } from '@/stores/useTaskStore'
import { generateId } from '@/lib/utils'
import type { LessonPlan } from '@/types'

export function useLessonPlans() {
  return useQuery({
    queryKey: ['lessonPlans'],
    queryFn: lessonPlansApi.getLessonPlans,
  })
}

export function useLessonPlan(id: string | undefined) {
  return useQuery({
    queryKey: ['lessonPlan', id],
    queryFn: () => lessonPlansApi.getLessonPlan(id!),
    enabled: !!id,
  })
}

export function useUpdateLessonPlan() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string
      data: Partial<LessonPlan>
    }) => lessonPlansApi.updateLessonPlan(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['lessonPlans'] })
      queryClient.invalidateQueries({ queryKey: ['lessonPlan', id] })
    },
  })
}

export function useDeleteLessonPlan() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: lessonPlansApi.deleteLessonPlan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lessonPlans'] })
    },
  })
}

export function useCreateLessonPlanStream() {
  const [isGenerating, setIsGenerating] = useState(false)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<LessonPlan | null>(null)
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

  const generate = useCallback(
    (request: lessonPlansApi.CreateLessonPlanRequest) => {
      const newTaskId = `lesson-plan-${generateId()}`
      setTaskId(newTaskId)
      setIsGenerating(true)
      setProgress(0)
      setResult(null)
      setError(null)

      startTask(newTaskId)

      saveCheckpoint(newTaskId, {
        taskId: newTaskId,
        taskType: 'lesson_plan',
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

      lessonPlansApi.createLessonPlanStream(
        request,
        (event) => {
          if (event.type === 'step' && event.step) {
            addStep(newTaskId, event.step)
          } else if (event.type === 'progress' && event.progress !== undefined) {
            setProgress(event.progress)
          } else if (event.type === 'result' && event.result) {
            setResult(event.result)
            queryClient.invalidateQueries({ queryKey: ['lessonPlans'] })
          } else if (event.type === 'error') {
            setError(event.error || 'Unknown error')
            failTask(newTaskId, event.error || 'Unknown error')
          }
        },
        (err) => {
          setError(err.message)
          failTask(newTaskId, err.message)
          setIsGenerating(false)
        },
        () => {
          completeTask(newTaskId)
          setIsGenerating(false)
        }
      )
    },
    [startTask, addStep, completeTask, failTask, saveCheckpoint, queryClient]
  )

  const pause = useCallback(() => {
    if (taskId) {
      pauseTask(taskId)
      lessonPlansApi.pauseLessonPlanTask(taskId).catch(console.error)
      setIsGenerating(false)
    }
  }, [taskId, pauseTask])

  const resume = useCallback(async () => {
    if (taskId) {
      const checkpoint = getCheckpoint(taskId)
      if (checkpoint) {
        setIsGenerating(true)
        await lessonPlansApi.resumeLessonPlanTask(taskId)
      }
    }
  }, [taskId, getCheckpoint])

  return {
    generate,
    pause,
    resume,
    isGenerating,
    progress,
    result,
    error,
    taskId,
  }
}
