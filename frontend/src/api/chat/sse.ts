import { streamChatWs } from '@/api/ws'
import type { BackendChatStreamEvent, ChatStreamEvent, SendMessageRequest } from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function recordValue(value: unknown, key: string): unknown {
  return isRecord(value) ? value[key] : undefined
}

function toBackendChatStreamEvent(value: unknown): BackendChatStreamEvent {
  if (isRecord(value)) return value as BackendChatStreamEvent
  return { type: 'error', content: String(value || 'unknown_error') }
}

function streamEventType(value: BackendChatStreamEvent): string {
  const type = recordValue(value, 'type')
  return typeof type === 'string' ? type : 'error'
}

function streamEventContent(value: BackendChatStreamEvent, fallback: string): string {
  const content = recordValue(value, 'content')
  if (typeof content === 'string' && content.trim()) return content

  const error = recordValue(value, 'error')
  if (typeof error === 'string' && error.trim()) return error

  const data = recordValue(value, 'data')
  const dataError = recordValue(data, 'error')
  if (typeof dataError === 'string' && dataError.trim()) return dataError

  const dataMessage = recordValue(data, 'message')
  if (typeof dataMessage === 'string' && dataMessage.trim()) return dataMessage

  return fallback
}

export function normalizeChatStreamEvent(data: unknown): ChatStreamEvent {
  const raw = toBackendChatStreamEvent(data)
  const type = streamEventType(raw)

  if (type === 'text_delta') {
    return { type: 'text_delta', raw, delta: streamEventContent(raw, '') }
  }

  if (type === 'error') {
    return { type: 'error', raw, error: streamEventContent(raw, 'unknown_error') }
  }

  return { type: type as ChatStreamEvent['type'], raw }
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

  const cleanup = streamChatWs(
    {
      conversation_id: conversationId,
      content: request.content,
      subject: request.subject,
      model: request.model,
      sub_model: request.subModel,
    },
    (data) => onEvent(normalizeChatStreamEvent(data)),
    onError,
    onComplete,
    { signal: options?.signal }
  )

  if (options?.signal) {
    options.signal.addEventListener('abort', () => cleanup())
  }
}
