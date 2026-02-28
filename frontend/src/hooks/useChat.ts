import { useState, useCallback, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as chatApi from '@/api/chat'
import { useTaskStore } from '@/stores/useTaskStore'
import { generateId } from '@/lib/utils'
import type { Message, TaskStep } from '@/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function normalizeError(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value.trim()
  return null
}

function inferToolResultStatus(result: unknown): { ok: boolean; error: string | null } {
  if (!isRecord(result)) return { ok: true, error: null }

  const success = result.success
  if (typeof success === 'boolean') {
    const err = normalizeError(result.error)
    return { ok: success, error: success ? null : err || 'tool_failed' }
  }

  const err = normalizeError(result.error)
  if (err) return { ok: false, error: err }

  return { ok: true, error: null }
}

export function useConversations() {
  return useQuery({
    queryKey: ['conversations'],
    queryFn: () => chatApi.getConversations(),
  })
}

export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: ['conversation', id],
    queryFn: () => chatApi.getConversation(id!),
    enabled: !!id,
  })
}

export function useMessages(conversationId: string | undefined) {
  return useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => chatApi.getMessages(conversationId!),
    enabled: !!conversationId,
    refetchOnWindowFocus: false,
  })
}

export function useCreateConversation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: chatApi.createConversation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useDeleteConversation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: chatApi.deleteConversation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useChatStream() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const queryClient = useQueryClient()
  const { startTask, addStep, updateStep, completeTask, failTask } = useTaskStore()

  const streamAbortRef = useRef<AbortController | null>(null)
  const streamKeyRef = useRef<string | null>(null)
  const taskIdRef = useRef<string | null>(null)

  const cancelStream = useCallback(
    (reason = 'cancelled') => {
      // Ensure any in-flight callbacks become no-ops.
      streamKeyRef.current = null

      if (streamAbortRef.current) {
        streamAbortRef.current.abort()
        streamAbortRef.current = null
      }

      if (taskIdRef.current) {
        failTask(taskIdRef.current, reason)
        taskIdRef.current = null
      }

      setIsStreaming(false)
    },
    [failTask]
  )

  useEffect(() => {
    return () => {
      cancelStream('unmounted')
    }
  }, [cancelStream])

  const sendMessage = useCallback(
    (conversationId: string, content: string) => {
      if (!content.trim()) return
      if (isStreaming) return

      cancelStream('replaced')
      const controller = new AbortController()
      streamAbortRef.current = controller
      const streamKey = generateId()
      streamKeyRef.current = streamKey

      const taskId = `chat-${conversationId}-${Date.now()}`
      taskIdRef.current = taskId
      
      const userMessage: Message = {
        id: generateId(),
        role: 'user',
        content,
        createdAt: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, userMessage])

      startTask(taskId)
      setIsStreaming(true)
      setError(null)

      const assistantMessage: Message = {
        id: generateId(),
        role: 'assistant',
        content: '',
        createdAt: new Date().toISOString(),
        steps: [],
      }
      setMessages((prev) => [...prev, assistantMessage])

      chatApi.sendMessageStream(
        { conversationId, content },
        (event) => {
          if (streamKeyRef.current !== streamKey) return

          if (event.type === 'text_delta') {
            const delta = event.delta || ''
            if (!delta) return
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessage.id ? { ...m, content: m.content + delta } : m
              )
            )
            return
          }

          if (event.type === 'tool_start') {
            const raw = event.raw as any
            const toolCallId = String(raw?.tool_call_id || generateId())
            const toolName = String(raw?.tool_name || 'tool')
            const now = new Date().toISOString()

            const step: TaskStep = {
              id: toolCallId,
              title: `调用工具：${toolName}`,
              status: 'running',
              toolName,
              input: raw?.arguments,
              startTime: now,
            }

            addStep(taskId, step)
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessage.id
                  ? { ...m, steps: [...(m.steps || []), step] }
                  : m
              )
            )
            return
          }

          if (event.type === 'tool_result') {
            const raw = event.raw as any
            const toolCallId = String(raw?.tool_call_id || '')
            if (!toolCallId) return

            const toolName = String(raw?.tool_name || 'tool')
            const result = raw?.result
            const { ok, error: toolError } = inferToolResultStatus(result)
            const status: TaskStep['status'] = ok ? 'completed' : 'failed'
            const now = new Date().toISOString()

            updateStep(taskId, toolCallId, {
              status,
              endTime: now,
              output: result,
              error: toolError || undefined,
              toolName,
            })

            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== assistantMessage.id) return m
                const steps = (m.steps || []).map((s) =>
                  s.id === toolCallId
                    ? {
                        ...s,
                        status,
                        endTime: now,
                        output: result,
                        error: toolError || undefined,
                        toolName,
                      }
                    : s
                )
                return { ...m, steps }
              })
            )
            return
          }

          if (event.type === 'assistant_final') {
            const raw = event.raw as any
            const finalText = String(raw?.content || '')
            if (!finalText) return
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id !== assistantMessage.id) return m
                // Prefer the longer one to avoid overwriting stream deltas with a shorter payload.
                if ((m.content || '').length >= finalText.length) return m
                return { ...m, content: finalText }
              })
            )
            return
          }

          if (event.type === 'error') {
            const msg = event.error || 'Unknown error'
            setError(msg)
            failTask(taskId, msg)
          }
        },
        (err) => {
          if (streamKeyRef.current !== streamKey) return
          setError(err.message)
          failTask(taskId, err.message)
          setIsStreaming(false)
          streamAbortRef.current = null
          streamKeyRef.current = null
          taskIdRef.current = null
        },
        () => {
          if (streamKeyRef.current !== streamKey) return
          completeTask(taskId)
          setIsStreaming(false)
          streamAbortRef.current = null
          streamKeyRef.current = null
          taskIdRef.current = null
          // Refresh sidebar ordering/title (e.g. backend sets title on first message)
          queryClient.invalidateQueries({ queryKey: ['chatConversations'] })
        },
        { signal: controller.signal }
      )
    },
    [
      isStreaming,
      cancelStream,
      startTask,
      addStep,
      updateStep,
      completeTask,
      failTask,
      queryClient,
    ]
  )

  return {
    messages,
    setMessages,
    isStreaming,
    error,
    sendMessage,
    cancelStream,
  }
}
