import { describe, expect, it } from 'vitest'
import { normalizeMessagesWithSteps } from '../client'
import type { BackendMessage } from '../types'

describe('normalizeMessagesWithSteps', () => {
  it('keeps an interrupted assistant tool-call message visible when no final answer exists', () => {
    const raw: BackendMessage[] = [
      {
        id: 1,
        role: 'user',
        content: '数学高考模拟',
        tool_calls: null,
        tool_call_id: null,
        created_at: '2026-06-06T00:00:00',
      },
      {
        id: 2,
        role: 'assistant',
        content: '我先查询可用筛选条件。',
        tool_calls: [
          {
            id: 'call-1',
            type: 'function',
            function: {
              name: 'get_available_filters',
              arguments: '{"subject":"高中数学"}',
            },
          },
        ],
        tool_call_id: null,
        created_at: '2026-06-06T00:00:01',
      },
    ]

    expect(normalizeMessagesWithSteps(raw)).toEqual([
      expect.objectContaining({ id: '1', role: 'user', content: '数学高考模拟' }),
      expect.objectContaining({
        id: '2',
        role: 'assistant',
        content: '我先查询可用筛选条件。',
        steps: [
          expect.objectContaining({
            id: 'call-1',
            status: 'running',
            toolName: 'get_available_filters',
            input: { subject: '高中数学' },
          }),
        ],
      }),
    ])
  })

  it('does not duplicate the intermediate tool-call assistant when a final answer exists', () => {
    const raw: BackendMessage[] = [
      {
        id: 1,
        role: 'user',
        content: '数学高考模拟',
        tool_calls: null,
        tool_call_id: null,
        created_at: '2026-06-06T00:00:00',
      },
      {
        id: 2,
        role: 'assistant',
        content: '我先查询可用筛选条件。',
        tool_calls: [
          {
            id: 'call-1',
            type: 'function',
            function: {
              name: 'get_available_filters',
              arguments: '{"subject":"高中数学"}',
            },
          },
        ],
        tool_call_id: null,
        created_at: '2026-06-06T00:00:01',
      },
      {
        id: 3,
        role: 'tool',
        content: '',
        tool_calls: null,
        tool_call_id: 'call-1',
        created_at: '2026-06-06T00:00:02',
        tool_result_meta: { success: true, error: null, size: 10 },
      },
      {
        id: 4,
        role: 'assistant',
        content: '这是最终回答。',
        tool_calls: null,
        tool_call_id: null,
        created_at: '2026-06-06T00:00:03',
      },
    ]

    const messages = normalizeMessagesWithSteps(raw)
    expect(messages).toHaveLength(2)
    expect(messages[1]).toMatchObject({
      id: '4',
      role: 'assistant',
      content: '这是最终回答。',
      steps: [
        expect.objectContaining({
          id: 'call-1',
          status: 'completed',
          toolName: 'get_available_filters',
        }),
      ],
    })
  })

  it('updates interrupted assistant tool-call steps from persisted tool results', () => {
    const raw: BackendMessage[] = [
      {
        id: 1,
        role: 'user',
        content: '数学高考模拟',
        tool_calls: null,
        tool_call_id: null,
        created_at: '2026-06-06T00:00:00',
      },
      {
        id: 2,
        role: 'assistant',
        content: '我先搜索题目。',
        tool_calls: [
          {
            id: 'call-1',
            type: 'function',
            function: {
              name: 'search_questions',
              arguments: '{"keyword":"函数"}',
            },
          },
        ],
        tool_call_id: null,
        created_at: '2026-06-06T00:00:01',
      },
      {
        id: 3,
        role: 'tool',
        content: '',
        tool_calls: null,
        tool_call_id: 'call-1',
        created_at: '2026-06-06T00:00:02',
        tool_result_meta: { success: false, error: 'fallback_list_empty', size: 0 },
      },
    ]

    const messages = normalizeMessagesWithSteps(raw)
    expect(messages).toHaveLength(2)
    expect(messages[1]).toMatchObject({
      id: '2',
      role: 'assistant',
      content: '我先搜索题目。',
      steps: [
        expect.objectContaining({
          id: 'call-1',
          status: 'failed',
          error: 'fallback_list_empty',
          toolName: 'search_questions',
        }),
      ],
    })
  })

  it('keeps interrupted assistant tool-call steps visible when assistant content is empty', () => {
    const raw: BackendMessage[] = [
      {
        id: 1,
        role: 'user',
        content: '继续',
        tool_calls: null,
        tool_call_id: null,
        created_at: '2026-06-06T00:00:00',
      },
      {
        id: 2,
        role: 'assistant',
        content: '',
        tool_calls: [
          {
            id: 'call-1',
            type: 'function',
            function: {
              name: 'search_questions',
              arguments: '{"keyword":"导数"}',
            },
          },
        ],
        tool_call_id: null,
        created_at: '2026-06-06T00:00:01',
      },
    ]

    const messages = normalizeMessagesWithSteps(raw)
    expect(messages).toHaveLength(2)
    expect(messages[1]).toMatchObject({
      id: '2',
      role: 'assistant',
      content: '',
      steps: [
        expect.objectContaining({
          id: 'call-1',
          status: 'running',
          toolName: 'search_questions',
        }),
      ],
    })
  })

  it('drops persisted empty assistant messages that have no content or steps', () => {
    const raw: BackendMessage[] = [
      {
        id: 1,
        role: 'user',
        content: '你好',
        tool_calls: null,
        tool_call_id: null,
        created_at: '2026-06-06T00:00:00',
      },
      {
        id: 2,
        role: 'assistant',
        content: '',
        tool_calls: null,
        tool_call_id: null,
        created_at: '2026-06-06T00:00:01',
      },
    ]

    expect(normalizeMessagesWithSteps(raw)).toEqual([
      expect.objectContaining({ id: '1', role: 'user', content: '你好' }),
    ])
  })
})
