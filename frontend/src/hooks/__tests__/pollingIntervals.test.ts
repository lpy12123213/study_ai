import { describe, expect, it } from 'vitest'
import {
  DASHBOARD_REFETCH_INTERVAL_MS,
  DEFAULT_RESOURCE_REFETCH_INTERVAL_MS,
  RUNNING_TASKS_REFETCH_INTERVAL_MS,
  runningTasksQueryKey,
} from '@/hooks/useRunningTasks'

describe('polling interval contract', () => {
  it('keeps running tasks, dashboard, and default resource intervals centralized', () => {
    expect(RUNNING_TASKS_REFETCH_INTERVAL_MS).toBe(5_000)
    expect(DASHBOARD_REFETCH_INTERVAL_MS).toBe(15_000)
    expect(DEFAULT_RESOURCE_REFETCH_INTERVAL_MS).toBe(30_000)
  })

  it('keys running-task queries by limit to avoid cache collisions', () => {
    expect(runningTasksQueryKey(8)).not.toEqual(runningTasksQueryKey(50))
  })
})
