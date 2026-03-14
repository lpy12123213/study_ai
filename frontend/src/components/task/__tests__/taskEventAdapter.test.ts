import { describe, expect, it } from 'vitest'
import type { TaskStep } from '@/types'
import { taskEventToStep, upsertTaskStep } from '@/components/task/taskEventAdapter'

describe('taskEventAdapter', () => {
  it('maps structured progress events into stable updatable steps', () => {
    const step = taskEventToStep({
      taskId: 'ql-gen-1',
      seq: 3,
      type: 'progress',
      created_at: '2026-03-14T10:00:00Z',
      data: {
        progress: 44,
        stage_id: 'spec_search',
        stage_label: '规格搜索',
        stats: {
          kept_specs: 8,
          sample_seed_tags: ['参数变化', '分类讨论'],
        },
      },
    })

    expect(step).not.toBeNull()
    expect(step?.id).toBe('stage:spec_search')
    expect(step?.title).toBe('规格搜索')
    expect(step?.output).toEqual({
      kept_specs: 8,
      sample_seed_tags: ['参数变化', '分类讨论'],
    })
  })

  it('updates an existing step instead of appending duplicates', () => {
    const prev: TaskStep[] = [
      {
        id: 'stage:judge',
        title: '判题筛选',
        status: 'running',
        startTime: '2026-03-14T10:00:00Z',
      },
    ]

    const next = upsertTaskStep(prev, {
      id: 'stage:judge',
      title: '判题筛选',
      status: 'completed',
      startTime: '2026-03-14T10:00:00Z',
      endTime: '2026-03-14T10:00:08Z',
      output: { accepted: 2, rejected: 5 },
    })

    expect(next).toHaveLength(1)
    expect(next[0].status).toBe('completed')
    expect(next[0].endTime).toBe('2026-03-14T10:00:08Z')
    expect(next[0].output).toEqual({ accepted: 2, rejected: 5 })
  })
})
