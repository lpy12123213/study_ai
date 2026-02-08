import { useEffect, useRef, useCallback, useState } from 'react'
import { createSSEConnection } from '@/api/client'

interface UseSSEOptions<T> {
  url: string
  onMessage: (data: T) => void
  onError?: (error: Event) => void
  onComplete?: () => void
  enabled?: boolean
}

export function useSSE<T>({
  url,
  onMessage,
  onError,
  onComplete,
  enabled = true,
}: UseSSEOptions<T>) {
  const eventSourceRef = useRef<EventSource | null>(null)
  const [isConnected, setIsConnected] = useState(false)

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    eventSourceRef.current = createSSEConnection(
      url,
      (data) => {
        onMessage(data as T)
      },
      (error) => {
        setIsConnected(false)
        onError?.(error)
      },
      () => {
        setIsConnected(false)
        onComplete?.()
      }
    )

    setIsConnected(true)
  }, [url, onMessage, onError, onComplete])

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
      setIsConnected(false)
    }
  }, [])

  useEffect(() => {
    if (enabled) {
      connect()
    } else {
      disconnect()
    }

    return () => {
      disconnect()
    }
  }, [enabled, connect, disconnect])

  return {
    isConnected,
    connect,
    disconnect,
  }
}
