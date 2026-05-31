import type { ConversationItem, Message, TaskStep } from '@/types'

export interface BackendConversation {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export interface BackendMessage {
  id: number
  role: 'user' | 'assistant' | 'tool' | string
  content: string
  tool_calls: unknown[] | null
  tool_call_id: string | null
  created_at: string
  tool_result_meta?: { size?: number; success?: boolean | null; error?: string | null } | null
}

export interface BackendConversationMessagesResponse {
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

export interface ChatApiConversationsData {
  conversations: ConversationItem[]
}

export interface ChatApiMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatApiMessagePage extends Omit<MessagePage, 'messages'> {
  messages: ChatApiMessage[]
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
  | { type: 'thinking_delta'; content?: string }
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
    | 'thinking_delta'
    | 'assistant_final'
    | 'error'
  raw: BackendChatStreamEvent
  delta?: string
  step?: TaskStep
  error?: string
}
