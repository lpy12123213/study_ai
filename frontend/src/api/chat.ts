import { apiClient, fetchSSE } from './client'
import type { Message, ConversationItem, TaskStep } from '@/types'

export interface CreateConversationRequest {
  title?: string
}

export interface SendMessageRequest {
  conversationId: string
  content: string
}

export interface ChatStreamEvent {
  type: 'message' | 'step' | 'done' | 'error'
  data?: Partial<Message>
  step?: TaskStep
  error?: string
}

// Get all conversations
export async function getConversations(): Promise<ConversationItem[]> {
  const response = await apiClient.get<ConversationItem[]>('/conversations')
  return response.data
}

// Get a single conversation
export async function getConversation(id: string): Promise<ConversationItem> {
  const response = await apiClient.get<ConversationItem>(`/conversations/${id}`)
  return response.data
}

// Create a new conversation
export async function createConversation(
  data: CreateConversationRequest
): Promise<ConversationItem> {
  const response = await apiClient.post<ConversationItem>('/conversations', data)
  return response.data
}

// Delete a conversation
export async function deleteConversation(id: string): Promise<void> {
  await apiClient.delete(`/conversations/${id}`)
}

// Get messages for a conversation
export async function getMessages(conversationId: string): Promise<Message[]> {
  const response = await apiClient.get<Message[]>(
    `/conversations/${conversationId}/messages`
  )
  return response.data
}

// Send a message (streaming)
export function sendMessageStream(
  request: SendMessageRequest,
  onEvent: (event: ChatStreamEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void
): void {
  fetchSSE(
    '/chat/stream',
    request,
    (data) => {
      onEvent(data as ChatStreamEvent)
    },
    onError,
    onComplete
  )
}

// Send a message (non-streaming)
export async function sendMessage(request: SendMessageRequest): Promise<Message> {
  const response = await apiClient.post<Message>('/chat', request)
  return response.data
}
