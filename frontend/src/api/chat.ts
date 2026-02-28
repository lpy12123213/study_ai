import { apiClient, fetchSSE } from './client'
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
}

interface BackendConversationMessagesResponse {
  conversation: BackendConversation
  messages: BackendMessage[]
}

export interface CreateConversationRequest {
  title?: string
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

function toMessage(m: BackendMessage): Message | null {
  const role = (m.role || '').toLowerCase()
  if (role === 'tool') return null

  // Hide intermediate "assistant tool_call intent" messages.
  if (role === 'assistant' && Array.isArray(m.tool_calls) && m.tool_calls.length > 0) {
    return null
  }

  if (role !== 'user' && role !== 'assistant') return null

  return {
    id: String(m.id),
    role: role as 'user' | 'assistant',
    content: String(m.content || ''),
    createdAt: m.created_at,
  }
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

export async function getMessages(conversationId: string): Promise<Message[]> {
  const response = await apiClient.get<BackendConversationMessagesResponse>(
    `/conversations/${conversationId}/messages`
  )

  const messages = (response.data.messages || [])
    .map(toMessage)
    .filter(Boolean) as Message[]
  return messages
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
