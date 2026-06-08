import { useQuery } from '@tanstack/react-query'
import * as tasksApi from '@/api/tasks'

export const RUNNING_TASKS_QUERY_KEY = ['runningTasks'] as const
export const RUNNING_TASKS_REFETCH_INTERVAL_MS = 5_000
export const DASHBOARD_REFETCH_INTERVAL_MS = 15_000
export const DEFAULT_RESOURCE_REFETCH_INTERVAL_MS = 30_000

export function runningTasksQueryKey(limit = 8, status = 'running') {
  return [...RUNNING_TASKS_QUERY_KEY, { limit, status }] as const
}

export function useRunningTasks(options?: { enabled?: boolean; limit?: number; status?: string }) {
  const limit = options?.limit ?? 8
  const status = options?.status ?? 'running'
  return useQuery({
    queryKey: runningTasksQueryKey(limit, status),
    queryFn: () => tasksApi.listTasks({ status: status === 'all' ? undefined : status, limit }),
    enabled: options?.enabled ?? true,
    refetchInterval: RUNNING_TASKS_REFETCH_INTERVAL_MS,
    staleTime: 2_000,
  })
}
