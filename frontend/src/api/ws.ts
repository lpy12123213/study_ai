/**
 * WebSocket client for long-running task streaming.
 *
 * Provides a persistent connection that avoids SSE timeout issues.
 * Falls back to SSE if WebSocket connection fails.
 */

import { useAuthStore } from '@/stores/useAuthStore'
import { API_BASE_URL } from '@/api/instance'
import { createStreamEventBatcher } from '@/lib/streamEventBatcher'

const WS_RECONNECT_DELAY_MS = 1000
const WS_MAX_RECONNECT_ATTEMPTS = 3
const WS_PING_INTERVAL_MS = 25_000

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function eventType(event: unknown): string {
  if (!isRecord(event)) return ''
  return String(event.type || '').trim()
}

const IMMEDIATE_EVENT_TYPES = new Set(['tool_result', 'assistant_final', 'final', 'done', 'result', 'error'])

function shouldFlushImmediately(event: unknown): boolean {
  return IMMEDIATE_EVENT_TYPES.has(eventType(event))
}

function getWsBaseUrl(): string {
  // Convert http(s)://host:port/api to ws(s)://host:port/api
  const base = API_BASE_URL || window.location.origin + '/api'
  return base.replace(/^http/, 'ws')
}

export interface WsStreamOptions {
  signal?: AbortSignal
  onReconnecting?: () => void
}

/**
 * Stream task events via WebSocket with automatic reconnection.
 *
 * @param taskId - The task ID to stream
 * @param afterSeq - Resume from this sequence number
 * @param onMessage - Called for each event
 * @param onError - Called on unrecoverable error
 * @param onComplete - Called when stream ends normally
 * @param options - Additional options (signal for cancellation)
 */
export function streamTaskWs(
  taskId: string,
  afterSeq: number,
  onMessage: (data: unknown) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: WsStreamOptions
): () => void {
  const token = useAuthStore.getState().token || ''
  const wsBase = getWsBaseUrl()
  const encodedId = encodeURIComponent(taskId)
  const url = `${wsBase}/ws/tasks/${encodedId}?after_seq=${Math.max(0, afterSeq || 0)}&token=${encodeURIComponent(token)}`

  const batcher = createStreamEventBatcher(onMessage, { shouldFlushImmediately })

  let ws: WebSocket | null = null
  let reconnectAttempts = 0
  let lastSeq = afterSeq
  let pingInterval: ReturnType<typeof setInterval> | null = null
  let closed = false
  let completed = false

  const cleanup = () => {
    closed = true
    if (pingInterval) {
      clearInterval(pingInterval)
      pingInterval = null
    }
    if (ws) {
      try {
        ws.close()
      } catch {
        // ignore
      }
      ws = null
    }
    batcher.flush()
  }

  const connect = () => {
    if (closed) return

    try {
      ws = new WebSocket(url.replace(`after_seq=${Math.max(0, afterSeq || 0)}`, `after_seq=${lastSeq}`))
    } catch (err) {
      onError?.(err instanceof Error ? err : new Error('ws_connect_failed'))
      return
    }

    ws.onopen = () => {
      reconnectAttempts = 0
      // Start ping interval to keep connection alive
      if (pingInterval) clearInterval(pingInterval)
      pingInterval = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, WS_PING_INTERVAL_MS)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        // Track sequence for reconnection
        if (isRecord(data) && typeof data.seq === 'number' && data.seq > lastSeq) {
          lastSeq = data.seq
        }
        // Skip pong messages
        if (isRecord(data) && data.type === 'pong') return
        batcher.enqueue(data)
      } catch {
        // Non-JSON message, pass through
        batcher.enqueue(event.data)
      }
    }

    ws.onclose = (event) => {
      if (pingInterval) {
        clearInterval(pingInterval)
        pingInterval = null
      }

      if (closed || completed) return

      // Normal closure or task completed
      if (event.code === 1000 || event.code === 1001) {
        batcher.flush()
        onComplete?.()
        completed = true
        return
      }

      // Auth error - don't reconnect
      if (event.code === 4001 || event.code === 4003) {
        batcher.flush()
        onError?.(new Error(event.reason || 'unauthorized'))
        return
      }

      // Task not found
      if (event.code === 4004) {
        batcher.flush()
        onError?.(new Error('task_not_found'))
        return
      }

      // Unexpected close - try to reconnect
      if (reconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++
        options?.onReconnecting?.()
        setTimeout(() => connect(), WS_RECONNECT_DELAY_MS * reconnectAttempts)
      } else {
        batcher.flush()
        onError?.(new Error('ws_connection_lost'))
      }
    }

    ws.onerror = () => {
      // onerror is always followed by onclose, so we handle reconnection there
    }
  }

  // Handle abort signal
  if (options?.signal) {
    if (options.signal.aborted) {
      onComplete?.()
      return () => {}
    }
    options.signal.addEventListener('abort', () => {
      cleanup()
      onComplete?.()
    })
  }

  connect()

  // Return cleanup function
  return cleanup
}

/**
 * Check if WebSocket is available and likely to work.
 * Returns false if we're in an environment where WS might not work.
 */
export function isWebSocketAvailable(): boolean {
  return typeof WebSocket !== 'undefined'
}

/**
 * Stream chat messages via WebSocket.
 *
 * @param message - The chat message payload to send
 * @param onMessage - Called for each event from the server
 * @param onError - Called on error
 * @param onComplete - Called when the response stream ends
 * @param options - Additional options
 * @returns cleanup function
 */
export function streamChatWs(
  message: {
    conversation_id: number
    content: string
    subject?: string
    model?: string
    sub_model?: string
  },
  onMessage: (data: unknown) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: WsStreamOptions
): () => void {
  const token = useAuthStore.getState().token || ''
  const wsBase = getWsBaseUrl()
  const url = `${wsBase}/ws/chat?token=${encodeURIComponent(token)}`

  const batcher = createStreamEventBatcher(onMessage, { shouldFlushImmediately })

  let ws: WebSocket | null = null
  let closed = false
  let completed = false
  let pingInterval: ReturnType<typeof setInterval> | null = null

  const cleanup = () => {
    closed = true
    if (pingInterval) {
      clearInterval(pingInterval)
      pingInterval = null
    }
    if (ws) {
      try { ws.close() } catch { /* ignore */ }
      ws = null
    }
    batcher.flush()
  }

  const connect = () => {
    if (closed) return

    try {
      ws = new WebSocket(url)
    } catch (err) {
      onError?.(err instanceof Error ? err : new Error('ws_connect_failed'))
      return
    }

    ws.onopen = () => {
      // Send the chat message
      ws!.send(JSON.stringify({
        type: 'message',
        conversation_id: message.conversation_id,
        content: message.content,
        subject: message.subject,
        model: message.model,
        sub_model: message.sub_model,
      }))

      // Start ping keepalive
      pingInterval = setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, WS_PING_INTERVAL_MS)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (isRecord(data) && data.type === 'pong') return

        // Check for completion
        if (isRecord(data) && (data.type === 'done' || data.done === true)) {
          batcher.enqueue(data)
          batcher.flush()
          completed = true
          onComplete?.()
          cleanup()
          return
        }

        batcher.enqueue(data)
      } catch {
        batcher.enqueue(event.data)
      }
    }

    ws.onclose = (event) => {
      if (pingInterval) {
        clearInterval(pingInterval)
        pingInterval = null
      }

      if (closed || completed) return

      if (event.code === 1000 || event.code === 1001) {
        batcher.flush()
        onComplete?.()
        return
      }

      if (event.code === 4001 || event.code === 4003) {
        batcher.flush()
        onError?.(new Error(event.reason || 'unauthorized'))
        return
      }

      batcher.flush()
      onError?.(new Error(event.reason || 'ws_connection_closed'))
    }

    ws.onerror = () => {
      // onerror is always followed by onclose
    }
  }

  if (options?.signal) {
    if (options.signal.aborted) {
      onComplete?.()
      return () => {}
    }
    options.signal.addEventListener('abort', () => {
      cleanup()
      onComplete?.()
    })
  }

  connect()
  return cleanup
}
