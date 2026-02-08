import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as chatApi from '@/api/chat'
import { useTaskStore } from '@/stores/useTaskStore'
import { useConversationStore } from '@/stores/useConversationStore'
import { generateId } from '@/lib/utils'
import type { Message } from '@/types'

export function useConversations() {
  return useQuery({
    queryKey: ['conversations'],
    queryFn: chatApi.getConversations,
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

export function useChatStream(conversationId: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { startTask, addStep, completeTask, failTask } = useTaskStore()
  const updateConversation = useConversationStore((state) => state.updateConversation)

  const sendMessage = useCallback(
    (content: string) => {
      const taskId = `chat-${conversationId}-${Date.now()}`
      
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
          if (event.type === 'message' && event.data) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessage.id
                  ? { ...m, content: m.content + (event.data?.content || '') }
                  : m
              )
            )
          } else if (event.type === 'step' && event.step) {
            const step = event.step
            addStep(taskId, step)
            
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMessage.id
                  ? { ...m, steps: [...(m.steps || []), step] }
                  : m
              )
            )
          } else if (event.type === 'error') {
            setError(event.error || 'Unknown error')
            failTask(taskId, event.error || 'Unknown error')
          }
        },
        (err) => {
          setError(err.message)
          failTask(taskId, err.message)
          setIsStreaming(false)
        },
        () => {
          completeTask(taskId)
          setIsStreaming(false)
          updateConversation(conversationId, { updatedAt: new Date().toISOString() })
        }
      )
    },
    [conversationId, startTask, addStep, completeTask, failTask, updateConversation]
  )

  return {
    messages,
    setMessages,
    isStreaming,
    error,
    sendMessage,
  }
}
