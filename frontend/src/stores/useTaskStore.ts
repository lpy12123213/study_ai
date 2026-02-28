import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { TaskStep, ResumableTask } from '@/types'

const EMPTY_STEPS: TaskStep[] = []

interface TaskState {
  // Active tasks
  activeTasks: Map<string, TaskStep[]>
  
  // Checkpoints for resumable tasks
  checkpoints: Map<string, ResumableTask>
  
  // Task operations
  startTask: (taskId: string) => void
  addStep: (taskId: string, step: TaskStep) => void
  updateStep: (taskId: string, stepId: string, data: Partial<TaskStep>) => void
  completeTask: (taskId: string) => void
  failTask: (taskId: string, error: string) => void
  
  // Checkpoint operations (for resumable tasks)
  saveCheckpoint: (taskId: string, checkpoint: ResumableTask) => void
  getCheckpoint: (taskId: string) => ResumableTask | undefined
  removeCheckpoint: (taskId: string) => void
  
  // Pause/Resume operations
  pauseTask: (taskId: string) => void
  resumeTask: (taskId: string) => ResumableTask | undefined
  
  // Get task steps
  getTaskSteps: (taskId: string) => TaskStep[]
}

export const useTaskStore = create<TaskState>()(
  persist(
    (set, get) => ({
      activeTasks: new Map(),
      checkpoints: new Map(),
      
      startTask: (taskId) => {
        set((state) => {
          const newTasks = new Map(state.activeTasks)
          newTasks.set(taskId, [])
          return { activeTasks: newTasks }
        })
      },
      
      addStep: (taskId, step) => {
        set((state) => {
          const newTasks = new Map(state.activeTasks)
          const steps = newTasks.get(taskId) ?? EMPTY_STEPS
          newTasks.set(taskId, [...steps, step])
          return { activeTasks: newTasks }
        })
      },
      
      updateStep: (taskId, stepId, data) => {
        set((state) => {
          const newTasks = new Map(state.activeTasks)
          const steps = newTasks.get(taskId) ?? EMPTY_STEPS
          const updatedSteps = steps.map((s) =>
            s.id === stepId ? { ...s, ...data } : s
          )
          newTasks.set(taskId, updatedSteps)
          return { activeTasks: newTasks }
        })
      },
      
      completeTask: (taskId) => {
        set((state) => {
          const steps = state.activeTasks.get(taskId) ?? EMPTY_STEPS
          const updatedSteps = steps.map((s) =>
            s.status === 'running' ? { ...s, status: 'completed' as const } : s
          )
          const newTasks = new Map(state.activeTasks)
          newTasks.set(taskId, updatedSteps)
          
          // Remove checkpoint if exists
          const newCheckpoints = new Map(state.checkpoints)
          newCheckpoints.delete(taskId)
          
          return { activeTasks: newTasks, checkpoints: newCheckpoints }
        })
      },
      
      failTask: (taskId, error) => {
        set((state) => {
          const steps = state.activeTasks.get(taskId) ?? EMPTY_STEPS
          const updatedSteps = steps.map((s) =>
            s.status === 'running'
              ? { ...s, status: 'failed' as const, error }
              : s
          )
          const newTasks = new Map(state.activeTasks)
          newTasks.set(taskId, updatedSteps)
          return { activeTasks: newTasks }
        })
      },
      
      saveCheckpoint: (taskId, checkpoint) => {
        set((state) => {
          const newCheckpoints = new Map(state.checkpoints)
          newCheckpoints.set(taskId, checkpoint)
          return { checkpoints: newCheckpoints }
        })
      },
      
      getCheckpoint: (taskId) => {
        return get().checkpoints.get(taskId)
      },
      
      removeCheckpoint: (taskId) => {
        set((state) => {
          const newCheckpoints = new Map(state.checkpoints)
          newCheckpoints.delete(taskId)
          return { checkpoints: newCheckpoints }
        })
      },
      
      pauseTask: (taskId) => {
        const steps = get().activeTasks.get(taskId) ?? EMPTY_STEPS
        const completedSteps = steps.filter((s) => s.status === 'completed')
        const pendingSteps = steps.filter(
          (s) => s.status === 'pending' || s.status === 'running'
        )
        
        // Update running steps to paused
        set((state) => {
          const newTasks = new Map(state.activeTasks)
          const updatedSteps = steps.map((s) =>
            s.status === 'running' ? { ...s, status: 'paused' as const } : s
          )
          newTasks.set(taskId, updatedSteps)
          return { activeTasks: newTasks }
        })
        
        // Create checkpoint
        const checkpoint: ResumableTask = {
          taskId,
          taskType: 'blueprint', // Will be overwritten by caller
          status: 'paused',
          currentStep: completedSteps.length,
          totalSteps: steps.length,
          checkpoint: {
            completedSteps,
            pendingSteps: pendingSteps.map((s) => ({
              ...s,
              status: 'pending' as const,
            })),
            context: null,
          },
          canResume: true,
        }
        
        get().saveCheckpoint(taskId, checkpoint)
      },
      
      resumeTask: (taskId) => {
        return get().checkpoints.get(taskId)
      },
      
      getTaskSteps: (taskId) => {
        return get().activeTasks.get(taskId) ?? EMPTY_STEPS
      },
    }),
    {
      name: 'task-storage',
      partialize: (state) => ({
        activeTasks: Array.from(state.activeTasks.entries()),
        checkpoints: Array.from(state.checkpoints.entries()),
      }),
      merge: (persisted, current) => {
        const persistedState = persisted as {
          activeTasks?: [string, TaskStep[]][]
          checkpoints?: [string, ResumableTask][]
        }
        return {
          ...current,
          activeTasks: new Map(persistedState?.activeTasks || []),
          checkpoints: new Map(persistedState?.checkpoints || []),
        }
      },
    }
  )
)
