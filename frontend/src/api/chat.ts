import { apiClient, fetchSSE } from './client'
import { generateId } from '@/lib/utils'
import type { ConversationItem, Message, TaskStep } from '@/types'

interface BackendConversation {
  id: number
  title: string
  created_at: string
  updated_at: string
}

interface BackendMessage {
  id: number
  role: 'user' | 'assistant' | 'tool' | string
  content: string
  tool_calls: unknown[] | null
  tool_call_id: string | null
  created_at: string
  tool_result_meta?: { size?: number; success?: boolean | null; error?: string | null } | null
}

interface BackendConversationMessagesResponse {
  conversation: BackendConversation
  messages: BackendMessage[]
  paging?: {
    limit?: number
    before_id?: number
    next_before_id?: number
  }
}

export interface CreateConversationRequest {
  title?: string
}

export interface GetMessagesOptions {
  limit?: number
  beforeId?: number
}

export interface MessagePage {
  messages: Message[]
  nextBeforeId: number
  hasMore: boolean
}

export interface SendMessageRequest {
  conversationId: string
  content: string
  subject?: string
  model?: string
  subModel?: string
}

export type BackendChatStreamEvent =
  | { type: 'iteration'; round?: number; message?: string }
  | { type: 'assistant'; content?: string; tool_calls?: unknown[]; iteration?: number }
  | {
      type: 'tool_start'
      tool_call_id: string
      tool_name: string
      arguments?: unknown
      iteration?: number
    }
  | {
      type: 'tool_result'
      tool_call_id: string
      tool_name: string
      result?: unknown
      iteration?: number
    }
  | { type: 'stream_start'; iteration?: number }
  | { type: 'text_delta'; content?: string }
  | {
      type: 'assistant_final'
      content?: string
      total_iterations?: number
      max_reached?: boolean
    }
  | { type: 'error'; content?: string }
  | Record<string, unknown>

export interface ChatStreamEvent {
  type:
    | 'iteration'
    | 'assistant'
    | 'tool_start'
    | 'tool_result'
    | 'stream_start'
    | 'text_delta'
    | 'assistant_final'
    | 'error'
  raw: BackendChatStreamEvent
  delta?: string
  step?: TaskStep
  error?: string
}

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
    return JSON.parse(s)
  } catch {
    return null
  }
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
        const toolCallId = String((tc as any)?.id || '').trim() || generateId()
        const toolName = String((tc as any)?.function?.name || (tc as any)?.name || 'tool').trim()
        const rawArgs = (tc as any)?.function?.arguments

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

export function sendMessageStream(
  request: SendMessageRequest,
  onEvent: (event: ChatStreamEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: {
    signal?: AbortSignal
  }
): void {
  const conversationId = Number.parseInt(request.conversationId, 10)
  if (!Number.isFinite(conversationId) || conversationId <= 0) {
    onError?.(new Error('conversation_id_invalid'))
    return
  }

  fetchSSE(
    '/chat',
    {
      conversation_id: conversationId,
      message: request.content,
      subject: request.subject,
      model: request.model,
      sub_model: request.subModel,
    },
    (data) => {
      const raw = data as BackendChatStreamEvent
      const t = typeof (raw as any)?.type === 'string' ? ((raw as any).type as string) : 'error'

      if (t === 'text_delta') {
        onEvent({ type: 'text_delta', raw, delta: String((raw as any)?.content || '') })
        return
      }

      if (t === 'error') {
        onEvent({ type: 'error', raw, error: String((raw as any)?.content || 'unknown_error') })
        return
      }

      // Pass-through for other event types; the hook will interpret them.
      onEvent({ type: t as ChatStreamEvent['type'], raw })
    },
    onError,
    onComplete,
    { signal: options?.signal }
  )
}

export const chatApi = {
  getConversations: async (_scope?: string): Promise<{ data: any }> => ({
    data: { conversations: await getConversations(100) },
  }),
  getMessages: async (conversationId: string): Promise<{ data: any }> => ({
    data: await getMessages(conversationId),
  }),
}
