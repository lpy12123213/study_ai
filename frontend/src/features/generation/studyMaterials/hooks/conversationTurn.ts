import type { Dispatch, SetStateAction } from 'react'
import { useConversationStore } from '@/stores/useConversationStore'
import { generateId } from '@/lib/utils'
import type { ConversationItem } from '@/types'
import type { SubAgentActivity } from '@/features/generation/studyMaterials/types'

export interface BeginAssistantTurnParams {
  conversationId: string
  userText: string
  now: string
  addMessage: ReturnType<typeof useConversationStore.getState>['addMessage']
  setError: (next: unknown) => void
  setSubAgentActivities: Dispatch<SetStateAction<SubAgentActivity[]>>
  setActiveSubAgentTab: Dispatch<SetStateAction<string | null>>
}

/**
 * Appends the user message and an empty assistant placeholder for a new turn,
 * resetting transient error/sub-agent state. Returns the assistant message id
 * the stream should write into.
 */
export function beginAssistantTurn({
  conversationId,
  userText,
  now,
  addMessage,
  setError,
  setSubAgentActivities,
  setActiveSubAgentTab,
}: BeginAssistantTurnParams): string {
  addMessage(conversationId, {
    id: generateId(),
    role: 'user',
    content: userText,
    createdAt: now,
  })

  setError(null)
  setSubAgentActivities([])
  setActiveSubAgentTab(null)

  const assistantMessageId = generateId()
  addMessage(conversationId, {
    id: assistantMessageId,
    role: 'assistant',
    content: '',
    createdAt: now,
    steps: [],
  })

  return assistantMessageId
}

export interface EnsureConversationParams {
  activeConversationId: string | null
  title: string
  now: string
  addConversation: ReturnType<typeof useConversationStore.getState>['addConversation']
  setCurrentConversation: ReturnType<typeof useConversationStore.getState>['setCurrentConversation']
  setMessages: ReturnType<typeof useConversationStore.getState>['setMessages']
  updateConversation: ReturnType<typeof useConversationStore.getState>['updateConversation']
}

/**
 * Resolves the target conversation for a new generation: creates a fresh
 * study-materials conversation when none is active, otherwise resets the active
 * one. Clears any previous resumable stream state and returns the conversation id.
 */
export function ensureStudyMaterialsConversation({
  activeConversationId,
  title,
  now,
  addConversation,
  setCurrentConversation,
  setMessages,
  updateConversation,
}: EnsureConversationParams): string {
  let conversationId = activeConversationId
  if (!conversationId) {
    conversationId = generateId()
    const conversation: ConversationItem = {
      id: conversationId,
      title,
      type: 'study_materials',
      createdAt: now,
      updatedAt: now,
      status: 'active',
      resumable: false,
      progress: 0,
    }
    addConversation(conversation)
    setCurrentConversation(conversationId, 'study_materials')
    setMessages(conversationId, [])
  } else {
    updateConversation(conversationId, {
      title,
      updatedAt: now,
      status: 'active',
      progress: 0,
      activeStream: undefined,
      resumable: false,
    })
  }

  // Starting a new run clears any previous resumable stream state for this conversation.
  useConversationStore.getState().updateConversation(conversationId, {
    activeStream: undefined,
    resumable: false,
  })

  return conversationId
}
