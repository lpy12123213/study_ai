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
        stage_group: 'design',
        stage_order: 5,
        description: '把出题目标展开为候选规格并做 beam 筛选。',
        summary: 'kept_specs=8',
        stats: {
          kept_specs: 8,
          sample_seed_tags: ['参数变化', '分类讨论'],
        },
      },
    })

    expect(step).not.toBeNull()
    expect(step?.id).toBe('stage:spec_search')
    expect(step?.title).toBe('规格搜索')
    expect(step?.input).toMatchObject({
      stage_id: 'spec_search',
      stage_label: '规格搜索',
      stage_group: 'design',
      stage_order: 5,
      description: '把出题目标展开为候选规格并做 beam 筛选。',
      summary: 'kept_specs=8',
      progress: 44,
    })
    expect(step?.output).toEqual({
      summary: 'kept_specs=8',
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

  it('labels reasoning deltas so raw reason and trace fallback stay distinguishable', () => {
    const raw = taskEventToStep({
      taskId: 'ql-gen-1',
      seq: 9,
      type: 'reasoning_delta',
      created_at: '2026-03-20T10:00:00Z',
      data: {
        stage_id: 'draft_realization',
        stage_label: '草稿生成',
        source: 'raw',
        content: '先拆解题干约束，再生成答案。',
      },
    })

    const trace = taskEventToStep({
      taskId: 'ql-gen-1',
      seq: 10,
      type: 'reasoning_delta',
      created_at: '2026-03-20T10:00:01Z',
      data: {
        stage_id: 'judge',
        stage_label: '判题筛选',
        source: 'trace',
        content: '判题筛选 已完成一次模型调用。',
      },
    })

    expect(raw).not.toBeNull()
    expect(raw?.title).toContain('原始 Reason')
    expect(raw?.toolName).toBe('reasoning')
    expect(trace).not.toBeNull()
    expect(trace?.title).toContain('事件 Trace')
    expect(trace?.toolName).toBe('reasoning')
  })
})
