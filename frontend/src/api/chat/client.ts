import { apiClient } from '../client'
import { generateId } from '@/lib/utils'
import type { ConversationItem, Message, TaskStep } from '@/types'
import type {
  BackendConversation,
  BackendConversationMessagesResponse,
  BackendMessage,
  ChatApiConversationsData,
  ChatApiMessage,
  ChatApiMessagePage,
  CreateConversationRequest,
  GetMessagesOptions,
  MessagePage,
} from './types'

function toConversationItem(conv: BackendConversation): ConversationItem {
  return {
    id: String(conv.id),
    title: conv.title || '新对话',
    type: 'chat',
    createdAt: conv.created_at,
    updatedAt: conv.updated_at,
    status: 'active',
    resumable: false,
  }
}

function safeJsonParse(value: string): unknown | null {
  const s = String(value || '').trim()
  if (!s) return null
  try {
    return JSON.parse(s) as unknown
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function recordValue(value: unknown, key: string): unknown {
  return isRecord(value) ? value[key] : undefined
}

function toolCallParts(value: unknown): { id: string; name: string; args: unknown } {
  const fn = recordValue(value, 'function')
  const id = String(recordValue(value, 'id') || '').trim() || generateId()
  const name = String(recordValue(fn, 'name') || recordValue(value, 'name') || 'tool').trim()
  return { id, name, args: recordValue(fn, 'arguments') }
}

function normalizeToolArgs(rawArgs: unknown): unknown {
  if (typeof rawArgs === 'string') {
    const parsed = safeJsonParse(rawArgs)
    return parsed ?? rawArgs
  }
  return rawArgs
}

function toMessagesWithSteps(raw: BackendMessage[]): Message[] {
  const out: Message[] = []

  // Tool trace reconstruction:
  // - assistant(tool_calls) => create running steps
  // - tool(tool_call_id)    => mark completed/failed
  // - assistant(final)      => attach steps to this assistant message
  const stepsById: Record<string, TaskStep> = {}
  let currentSteps: TaskStep[] = []

  const commitAssistantSteps = (msg: Message) => {
    if (msg.role !== 'assistant') return msg
    if (!currentSteps.length) return msg
    msg.steps = currentSteps
    currentSteps = []
    for (const key of Object.keys(stepsById)) {
      delete stepsById[key]
    }
    return msg
  }

  for (const m of raw || []) {
    const role = String(m.role || '').toLowerCase()
    const createdAt = m.created_at

    if (role === 'assistant' && Array.isArray(m.tool_calls) && m.tool_calls.length > 0) {
      for (const tc of m.tool_calls) {
        const { id: toolCallId, name: toolName, args: rawArgs } = toolCallParts(tc)

        const step: TaskStep = {
          id: toolCallId,
          title: `调用工具：${toolName || 'tool'}`,
          status: 'running',
          toolName: toolName || undefined,
          input: normalizeToolArgs(rawArgs),
          startTime: createdAt || undefined,
        }

        stepsById[toolCallId] = step
        currentSteps.push(step)
      }
      continue
    }

    if (role === 'tool') {
      const toolCallId = String(m.tool_call_id || '').trim()
      if (!toolCallId) continue

      const step = stepsById[toolCallId]
      if (!step) continue

      const meta = m.tool_result_meta || null
      const ok = typeof meta?.success === 'boolean' ? meta.success : null
      const err = typeof meta?.error === 'string' && meta.error.trim() ? meta.error.trim() : null

      step.endTime = createdAt || undefined
      if (ok === false) {
        step.status = 'failed'
        step.error = err || 'tool_failed'
      } else if (ok === null && err) {
        step.status = 'failed'
        step.error = err
      } else if (ok === true) {
        step.status = 'completed'
      } else {
        // Fallback: if we cannot infer, mark completed (avoid "stuck running" after refresh).
        step.status = 'completed'
      }

      if (m.content) {
        step.output = safeJsonParse(m.content) ?? m.content
      } else if (meta) {
        step.output = meta
      }

      continue
    }

    if (role !== 'user' && role !== 'assistant') continue

    const msg: Message = {
      id: String(m.id),
      role: role as 'user' | 'assistant',
      content: String(m.content || ''),
      createdAt,
    }

    if (role === 'assistant') {
      commitAssistantSteps(msg)
    } else {
      // New user turn: drop any dangling steps to avoid leaking across turns.
      currentSteps = []
      for (const key of Object.keys(stepsById)) {
        delete stepsById[key]
      }
    }

    out.push(msg)
  }

  // If the last message isn't assistant_final (e.g. interrupted), attach what we have.
  if (currentSteps.length > 0 && out.length > 0) {
    const last = out[out.length - 1]
    if (last.role === 'assistant') {
      last.steps = [...(last.steps || []), ...currentSteps]
    }
  }

  return out
}

export async function getConversations(limit = 50): Promise<ConversationItem[]> {
  const response = await apiClient.get<BackendConversation[]>('/conversations', {
    params: { limit },
  })
  return response.data.map(toConversationItem)
}

export async function getConversation(id: string): Promise<ConversationItem> {
  const response = await apiClient.get<BackendConversationMessagesResponse>(
    `/conversations/${id}/messages`
  )
  return toConversationItem(response.data.conversation)
}

export async function createConversation(
  data: CreateConversationRequest
): Promise<ConversationItem> {
  const response = await apiClient.post<{ id: number; title: string }>(
    '/conversations',
    data
  )

  const now = new Date().toISOString()
  return {
    id: String(response.data.id),
    title: response.data.title || data.title || '新对话',
    type: 'chat',
    createdAt: now,
    updatedAt: now,
    status: 'active',
    resumable: false,
  }
}

export async function deleteConversation(id: string): Promise<void> {
  await apiClient.delete(`/conversations/${id}`)
}

export async function getMessages(
  conversationId: string,
  options: GetMessagesOptions = {}
): Promise<MessagePage> {
  const limit = Math.max(1, Math.min(options.limit ?? 100, 500))
  const beforeId = Math.max(0, Number(options.beforeId ?? 0) || 0)
  const response = await apiClient.get<BackendConversationMessagesResponse>(
    `/conversations/${conversationId}/messages`,
    {
      params: {
        limit,
        before_id: beforeId || undefined,
        include_trace: true,
        include_tool_content: false,
      },
    }
  )

  const raw = response.data.messages || []
  const nextBeforeId = Number(response.data.paging?.next_before_id ?? raw[0]?.id ?? 0) || 0
  return {
    messages: toMessagesWithSteps(raw),
    nextBeforeId,
    hasMore: raw.length >= limit && nextBeforeId > 0,
  }
}

export const chatApi = {
  getConversations: async (_scope?: string): Promise<{ data: ChatApiConversationsData }> => ({
    data: { conversations: await getConversations(100) },
  }),
  getMessages: async (conversationId: string): Promise<{ data: ChatApiMessagePage }> => {
    const page = await getMessages(conversationId)
    return {
      data: {
        ...page,
        messages: page.messages
          .filter((message): message is Message & ChatApiMessage => message.role === 'user' || message.role === 'assistant')
          .map((message) => ({ role: message.role, content: message.content })),
      },
    }
  },
}
