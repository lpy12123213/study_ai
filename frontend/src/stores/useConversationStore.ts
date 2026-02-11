import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ConversationItem, ConversationType, Message } from '@/types'

const EMPTY_MESSAGES: Message[] = []

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

interface ConversationState {
  conversations: ConversationItem[]
  currentConversationId: string | null
  filter: ConversationType | 'all'
  messagesByConversation: Record<string, Message[]>
  
  setConversations: (conversations: ConversationItem[]) => void
  addConversation: (conversation: ConversationItem) => void
  updateConversation: (id: string, data: Partial<ConversationItem>) => void
  removeConversation: (id: string) => void
  setCurrentConversation: (id: string | null) => void
  setFilter: (filter: ConversationType | 'all') => void

  // Local messages (used by non-chat Manus dialogs, e.g. lesson plans)
  getMessages: (conversationId: string) => Message[]
  setMessages: (conversationId: string, messages: Message[]) => void
  addMessage: (conversationId: string, message: Message) => void
  updateMessage: (
    conversationId: string,
    messageId: string,
    patch: Partial<Message>
  ) => void
  clearMessages: (conversationId: string) => void
  
  getFilteredConversations: () => ConversationItem[]
}

export const useConversationStore = create<ConversationState>()(
  persist(
    (set, get) => ({
      conversations: [],
      currentConversationId: null,
      filter: 'all',
      messagesByConversation: {},

      setConversations: (conversations) => set({ conversations }),

      addConversation: (conversation) =>
        set((state) => ({
          conversations: [conversation, ...state.conversations],
        })),

      updateConversation: (id, data) =>
        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.id === id ? { ...c, ...data } : c
          ),
        })),

      removeConversation: (id) =>
        set((state) => ({
          conversations: state.conversations.filter((c) => c.id !== id),
          currentConversationId:
            state.currentConversationId === id ? null : state.currentConversationId,
          messagesByConversation: (() => {
            const next = { ...state.messagesByConversation }
            delete next[id]
            return next
          })(),
        })),

      setCurrentConversation: (id) => set({ currentConversationId: id }),

      setFilter: (filter) => set({ filter }),

      getMessages: (conversationId) =>
        get().messagesByConversation[conversationId] ?? EMPTY_MESSAGES,

      setMessages: (conversationId, messages) =>
        set((state) => ({
          messagesByConversation: {
            ...state.messagesByConversation,
            [conversationId]: messages,
          },
        })),

      addMessage: (conversationId, message) =>
        set((state) => {
          const prev = state.messagesByConversation[conversationId] ?? EMPTY_MESSAGES
          return {
            messagesByConversation: {
              ...state.messagesByConversation,
              [conversationId]: [...prev, message],
            },
          }
        }),

      updateMessage: (conversationId, messageId, patch) =>
        set((state) => {
          const prev = state.messagesByConversation[conversationId] ?? EMPTY_MESSAGES
          const next = prev.map((m) => (m.id === messageId ? { ...m, ...patch } : m))
          return {
            messagesByConversation: {
              ...state.messagesByConversation,
              [conversationId]: next,
            },
          }
        }),

      clearMessages: (conversationId) =>
        set((state) => {
          const next = { ...state.messagesByConversation }
          delete next[conversationId]
          return { messagesByConversation: next }
        }),

      getFilteredConversations: () => {
        const { conversations, filter } = get()
        if (filter === 'all') return conversations
        return conversations.filter((c) => c.type === filter)
      },
    }),
    {
      name: 'conversation-storage',
      version: 2,
      migrate: (persistedState: unknown) => {
        const state = (persistedState || {}) as Partial<ConversationState>

        const conversations = Array.isArray(state.conversations)
          ? state.conversations.filter((c) => c && c.type !== 'chat')
          : []
        const allowedIds = new Set(conversations.map((c) => c.id))

        const rawMessages = isRecord(state.messagesByConversation) ? state.messagesByConversation : {}
        const messagesByConversation: Record<string, Message[]> = {}
        for (const [id, messages] of Object.entries(rawMessages)) {
          if (!allowedIds.has(id)) continue
          if (Array.isArray(messages)) messagesByConversation[id] = messages as Message[]
        }

        const currentConversationId =
          state.currentConversationId && allowedIds.has(state.currentConversationId)
            ? state.currentConversationId
            : null

        return {
          ...state,
          conversations,
          currentConversationId,
          messagesByConversation,
          filter: (state.filter as any) || 'all',
        } as ConversationState
      },
      partialize: (state) => {
        const conversations = (state.conversations || []).filter((c) => c.type !== 'chat')
        const allowedIds = new Set(conversations.map((c) => c.id))
        const messagesByConversation = Object.fromEntries(
          Object.entries(state.messagesByConversation || {}).filter(([id]) => allowedIds.has(id))
        ) as Record<string, Message[]>

        return {
          conversations,
          currentConversationId: state.currentConversationId,
          filter: state.filter,
          messagesByConversation,
        }
      },
    }
  )
)
