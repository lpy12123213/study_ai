import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as chatApi from '@/api/chat'
import { useTaskStore } from '@/stores/useTaskStore'
import { generateId } from '@/lib/utils'
import { isRecord } from '@/lib/record'
import type { Message, TaskStep } from '@/types'

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

function recordValue(value: unknown, key: string): unknown {
  return isRecord(value) ? value[key] : undefined
}

function streamContent(raw: unknown): string {
  if (!isRecord(raw)) return ''
  const content = raw.content
  return typeof content === 'string' ? content.trim() : ''
}

function streamIterationMessage(raw: unknown): string {
  if (!isRecord(raw)) return ''
  const message = raw.message
  if (typeof message === 'string' && message.trim()) return message.trim()

  const round = Number(raw.round ?? raw.iteration)
  if (Number.isFinite(round) && round > 0) {
    return `AI 正在进行第 ${round} 轮操作...`
  }
  return ''
}

function commitOrDropAssistantPlaceholder(prev: Message[], messageId: string, content: string): Message[] {
  if (!content.trim()) {
    return prev.filter((m) => m.id !== messageId)
  }
  return prev.map((m) => (m.id === messageId ? { ...m, content } : m))
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
  const query = useInfiniteQuery({
    queryKey: ['messages', conversationId],
    queryFn: ({ pageParam }) =>
      chatApi.getMessages(conversationId!, {
        limit: 100,
        beforeId: typeof pageParam === 'number' ? pageParam : 0,
      }),
    enabled: !!conversationId,
    initialPageParam: 0,
    getNextPageParam: (lastPage) => (lastPage.hasMore ? lastPage.nextBeforeId : undefined),
    refetchOnWindowFocus: false,
  })

  const messages = useMemo(() => {
    const pages = query.data?.pages || []
    return pages.flatMap((page) => page.messages)
  }, [query.data])

  return {
    ...query,
    messages,
  }
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
  const [streamingMessageId, setStreamingMessageId] = useState<string>('')
  const [streamingText, setStreamingText] = useState<string>('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const queryClient = useQueryClient()
  const { startTask, addStep, updateStep, completeTask, failTask } = useTaskStore()

  const streamAbortRef = useRef<AbortController | null>(null)
  const streamKeyRef = useRef<string | null>(null)
  const taskIdRef = useRef<string | null>(null)
  const streamingTextRef = useRef('')
  const streamingMessageIdRef = useRef('')
  const streamingTextIsProgressRef = useRef(false)
  const cancelStreamRef = useRef<(reason?: string) => void>(() => {})
  const unmountCancelTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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

      const committedId = streamingMessageIdRef.current
      if (committedId) {
        const committedText = streamingTextIsProgressRef.current ? '' : streamingTextRef.current
        setMessages((prev) => commitOrDropAssistantPlaceholder(prev, committedId, committedText))
      }

      streamingTextRef.current = ''
      streamingMessageIdRef.current = ''
      streamingTextIsProgressRef.current = false
      setStreamingText('')
      setStreamingMessageId('')
      setIsStreaming(false)
    },
    [failTask]
  )

  useEffect(() => {
    cancelStreamRef.current = cancelStream
  }, [cancelStream])

  useEffect(() => {
    if (unmountCancelTimerRef.current !== null) {
      clearTimeout(unmountCancelTimerRef.current)
      unmountCancelTimerRef.current = null
    }

    return () => {
      unmountCancelTimerRef.current = setTimeout(() => {
        unmountCancelTimerRef.current = null
        cancelStreamRef.current('unmounted')
      }, 0)
    }
  }, [])

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
      streamingTextRef.current = ''
      streamingMessageIdRef.current = assistantMessage.id
      streamingTextIsProgressRef.current = false
      setStreamingText('')
      setStreamingMessageId(assistantMessage.id)
      setMessages((prev) => [...prev, assistantMessage])

      let deltaBuffer = ''
      let deltaRaf: number | null = null

      const flushDeltas = () => {
        if (streamKeyRef.current !== streamKey) {
          deltaBuffer = ''
          return
        }
        if (!deltaBuffer) return
        const chunk = deltaBuffer
        deltaBuffer = ''
        if (streamingTextIsProgressRef.current) {
          streamingTextRef.current = ''
          streamingTextIsProgressRef.current = false
        }
        streamingTextRef.current += chunk
        setStreamingText(streamingTextRef.current)
      }

      const scheduleFlush = () => {
        if (deltaRaf != null) return
        deltaRaf = requestAnimationFrame(() => {
          deltaRaf = null
          flushDeltas()
        })
      }

      const setAssistantProgressText = (text: string) => {
        const progressText = text.trim()
        if (!progressText) return
        if (!streamingTextIsProgressRef.current && streamingTextRef.current) return
        streamingTextIsProgressRef.current = true
        streamingTextRef.current = progressText
        setStreamingText(progressText)
      }

      chatApi.sendMessageStream(
        { conversationId, content },
        (event) => {
          if (streamKeyRef.current !== streamKey) return

          if (event.type === 'text_delta') {
            const delta = event.delta || ''
            if (!delta) return
            deltaBuffer += delta
            scheduleFlush()
            return
          }

          if (event.type === 'stream_start') {
            const iteration = Number(recordValue(event.raw, 'iteration'))
            setAssistantProgressText(
              Number.isFinite(iteration) && iteration > 0
                ? `第 ${iteration} 轮：正在规划回答...`
                : '正在思考...'
            )
            return
          }

          if (event.type === 'thinking_delta') {
            setAssistantProgressText('正在梳理思路...')
            return
          }

          if (event.type === 'iteration') {
            setAssistantProgressText(streamIterationMessage(event.raw))
            return
          }

          if (event.type === 'assistant') {
            setAssistantProgressText(streamContent(event.raw))
            return
          }

          if (event.type === 'tool_start') {
            const raw = event.raw
            // BackendChatStreamEvent is a discriminated union; use the matching branch's type.
            const toolStart = raw.type === 'tool_start' ? raw : null
            const toolCallId = String(toolStart?.tool_call_id || generateId())
            const toolName = String(toolStart?.tool_name || 'tool')
            const now = new Date().toISOString()

            const step: TaskStep = {
              id: toolCallId,
              title: toolName,
              status: 'running',
              toolName,
              input: toolStart?.arguments,
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
            const raw = event.raw
            const toolResult = raw.type === 'tool_result' ? raw : null
            const toolCallId = String(toolResult?.tool_call_id || '')
            if (!toolCallId) return

            const toolName = String(toolResult?.tool_name || 'tool')
            const result: unknown = toolResult?.result
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
            const raw = event.raw
            const final = raw.type === 'assistant_final' ? raw : null
            const finalText = String(final?.content || '')
            if (!finalText) return
            deltaBuffer = ''
            if (deltaRaf != null) {
              cancelAnimationFrame(deltaRaf)
              deltaRaf = null
            }
            if (streamingTextRef.current !== finalText) {
              streamingTextIsProgressRef.current = false
              streamingTextRef.current = finalText
              setStreamingText(finalText)
            }
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
          const msg = err instanceof Error ? err.message : String(err || 'stream_failed')
          setError(err)
          failTask(taskId, msg)
          if (deltaRaf != null) {
            cancelAnimationFrame(deltaRaf)
            deltaRaf = null
            flushDeltas()
          }
          if (streamingMessageIdRef.current) {
            const committedText = streamingTextIsProgressRef.current ? '' : streamingTextRef.current
            const committedId = streamingMessageIdRef.current
            setMessages((prev) => commitOrDropAssistantPlaceholder(prev, committedId, committedText))
          }
          streamingTextRef.current = ''
          streamingMessageIdRef.current = ''
          streamingTextIsProgressRef.current = false
          setStreamingText('')
          setStreamingMessageId('')
          setIsStreaming(false)
          streamAbortRef.current = null
          streamKeyRef.current = null
          taskIdRef.current = null
        },
        () => {
          if (streamKeyRef.current !== streamKey) return
          if (deltaRaf != null) {
            cancelAnimationFrame(deltaRaf)
            deltaRaf = null
            flushDeltas()
          }
          const committedText = streamingTextIsProgressRef.current ? '' : streamingTextRef.current
          const committedId = streamingMessageIdRef.current
          if (committedId) {
            setMessages((prev) => commitOrDropAssistantPlaceholder(prev, committedId, committedText))
          }
          streamingTextRef.current = ''
          streamingMessageIdRef.current = ''
          streamingTextIsProgressRef.current = false
          setStreamingText('')
          setStreamingMessageId('')
          completeTask(taskId)
          setIsStreaming(false)
          streamAbortRef.current = null
          streamKeyRef.current = null
          taskIdRef.current = null
          // Refresh sidebar ordering/title (e.g. backend sets title on first message)
          queryClient.invalidateQueries({ queryKey: ['conversations'] })
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
    streamingMessageId,
    streamingText,
    isStreaming,
    error,
    sendMessage,
    cancelStream,
  }
}
