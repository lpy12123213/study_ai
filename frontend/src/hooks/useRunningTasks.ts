import { useQuery } from '@tanstack/react-query'
import * as tasksApi from '@/api/tasks'

export const RUNNING_TASKS_QUERY_KEY = ['runningTasks'] as const

export function useRunningTasks(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: RUNNING_TASKS_QUERY_KEY,
    queryFn: () => tasksApi.listTasks({ status: 'running', limit: 8 }),
    enabled: options?.enabled ?? true,
    refetchInterval: 5_000,
    staleTime: 2_000,
  })
}
