import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ConversationItem, ConversationType, Message } from '@/types'

const EMPTY_MESSAGES: Message[] = []

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
      partialize: (state) => ({
        conversations: state.conversations,
        currentConversationId: state.currentConversationId,
        filter: state.filter,
        messagesByConversation: state.messagesByConversation,
      }),
    }
  )
)
