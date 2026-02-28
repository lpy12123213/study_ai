import { useEffect, useRef, useCallback, useState } from 'react'
import { fetchSSERequest } from '@/api/client'

interface UseSSEOptions<T> {
  url: string
  onMessage: (data: T) => void
  onError?: (error: Error) => void
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
  const abortRef = useRef<AbortController | null>(null)
  const [isConnected, setIsConnected] = useState(false)

  const onMessageRef = useRef(onMessage)
  const onErrorRef = useRef(onError)
  const onCompleteRef = useRef(onComplete)

  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    onErrorRef.current = onError
  }, [onError])

  useEffect(() => {
    onCompleteRef.current = onComplete
  }, [onComplete])

  const connect = useCallback(() => {
    setIsConnected(true)

    if (abortRef.current) {
      abortRef.current.abort()
    }
    const controller = new AbortController()
    abortRef.current = controller

    fetchSSERequest(
      url,
      { method: 'GET', signal: controller.signal },
      (data) => {
        onMessageRef.current(data as T)
      },
      (error) => {
        setIsConnected(false)
        onErrorRef.current?.(error)
      },
      () => {
        setIsConnected(false)
        onCompleteRef.current?.()
      }
    )
  }, [url])

  const disconnect = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    setIsConnected(false)
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
