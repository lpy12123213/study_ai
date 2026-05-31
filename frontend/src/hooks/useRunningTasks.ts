import { useQuery } from '@tanstack/react-query'
import * as tasksApi from '@/api/tasks'

export const RUNNING_TASKS_QUERY_KEY = ['runningTasks'] as const
export const RUNNING_TASKS_REFETCH_INTERVAL_MS = 5_000
export const DASHBOARD_REFETCH_INTERVAL_MS = 15_000
export const DEFAULT_RESOURCE_REFETCH_INTERVAL_MS = 30_000

export function runningTasksQueryKey(limit = 8) {
  return [...RUNNING_TASKS_QUERY_KEY, { limit }] as const
}

export function useRunningTasks(options?: { enabled?: boolean; limit?: number }) {
  const limit = options?.limit ?? 8
  return useQuery({
    queryKey: runningTasksQueryKey(limit),
    queryFn: () => tasksApi.listTasks({ status: 'running', limit }),
    enabled: options?.enabled ?? true,
    refetchInterval: RUNNING_TASKS_REFETCH_INTERVAL_MS,
    staleTime: 2_000,
  })
}
