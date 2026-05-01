import { describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
import { getTask } from '@/api/tasks'

vi.mock('@/api/client', () => ({
  apiClient: {
    get: vi.fn(),
  },
  fetchSSERequest: vi.fn(),
}))

describe('tasks api', () => {
  it('requests persisted events when fetching a task snapshot', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { id: 'task-1', events: [] } })

    await getTask('task-1', { includeEvents: true, eventsLimit: 25 })

    expect(apiClient.get).toHaveBeenCalledWith('/tasks/task-1', {
      params: {
        include_events: true,
        events_limit: 25,
      },
    })
  })
})
