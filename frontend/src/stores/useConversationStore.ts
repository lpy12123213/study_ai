import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { sanitizeMessageForState, sanitizeMessagesForPersist, sanitizeMessagesForState } from '@/lib/taskPayload'
import type { ConversationItem, ConversationType, Message } from '@/types'

const EMPTY_MESSAGES: Message[] = []

const MAX_CONVERSATIONS = 50
const MAX_MESSAGES_PER_CONVERSATION = 200

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

type LocalConversationType = Exclude<ConversationType, 'chat'>

const DEFAULT_CURRENT_BY_TYPE: Record<LocalConversationType, string | null> = {
  blueprint: null,
  lesson_plan: null,
  study_materials: null,
}

interface ConversationState {
  conversations: ConversationItem[]
  currentConversationIdByType: Record<LocalConversationType, string | null>
  filter: ConversationType | 'all'
  messagesByConversation: Record<string, Message[]>
  
  setConversations: (conversations: ConversationItem[]) => void
  addConversation: (conversation: ConversationItem) => void
  updateConversation: (id: string, data: Partial<ConversationItem>) => void
  removeConversation: (id: string) => void
  setCurrentConversation: (id: string | null, type: LocalConversationType) => void
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

function trimMessages(messages: Message[]): Message[] {
  if (!Array.isArray(messages)) return EMPTY_MESSAGES
  if (messages.length <= MAX_MESSAGES_PER_CONVERSATION) return messages
  return messages.slice(-MAX_MESSAGES_PER_CONVERSATION)
}

function normalizeMessages(messages: Message[]): Message[] {
  return trimMessages(sanitizeMessagesForState(messages))
}

export const useConversationStore = create<ConversationState>()(
  persist(
    (set, get) => ({
      conversations: [],
      currentConversationIdByType: { ...DEFAULT_CURRENT_BY_TYPE },
      filter: 'all',
      messagesByConversation: {},

      setConversations: (conversations) => set({ conversations }),

      addConversation: (conversation) =>
        set((state) => {
          const conversations = [conversation, ...state.conversations].slice(0, MAX_CONVERSATIONS)
          const allowedIds = new Set(conversations.map((c) => c.id))

          const messagesByConversation = Object.fromEntries(
            Object.entries(state.messagesByConversation).filter(([id]) => allowedIds.has(id))
          ) as Record<string, Message[]>

          const currentConversationIdByType = Object.fromEntries(
            Object.entries(state.currentConversationIdByType).map(([t, cur]) => [
              t,
              typeof cur === 'string' && allowedIds.has(cur) ? cur : null,
            ])
          ) as ConversationState['currentConversationIdByType']

          return { conversations, messagesByConversation, currentConversationIdByType }
        }),

      updateConversation: (id, data) =>
        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.id === id ? { ...c, ...data } : c
          ),
        })),

      removeConversation: (id) =>
        set((state) => ({
          conversations: state.conversations.filter((c) => c.id !== id),
          currentConversationIdByType: Object.fromEntries(
            Object.entries(state.currentConversationIdByType).map(([t, cur]) => [
              t,
              cur === id ? null : cur,
            ])
          ) as ConversationState['currentConversationIdByType'],
          messagesByConversation: (() => {
            const next = { ...state.messagesByConversation }
            delete next[id]
            return next
          })(),
        })),

      setCurrentConversation: (id, type) =>
        set((state) => ({
          currentConversationIdByType: {
            ...state.currentConversationIdByType,
            [type]: id,
          },
        })),

      setFilter: (filter) => set({ filter }),

      getMessages: (conversationId) =>
        get().messagesByConversation[conversationId] ?? EMPTY_MESSAGES,

      setMessages: (conversationId, messages) =>
        set((state) => ({
          messagesByConversation: {
            ...state.messagesByConversation,
            [conversationId]: normalizeMessages(messages),
          },
        })),

      addMessage: (conversationId, message) =>
        set((state) => {
          const prev = state.messagesByConversation[conversationId] ?? EMPTY_MESSAGES
          const nextMessages = normalizeMessages([...prev, sanitizeMessageForState(message)])
          return {
            messagesByConversation: {
              ...state.messagesByConversation,
              [conversationId]: nextMessages,
            },
          }
        }),

      updateMessage: (conversationId, messageId, patch) =>
        set((state) => {
          const prev = state.messagesByConversation[conversationId] ?? EMPTY_MESSAGES
          const next = prev.map((m) =>
            m.id === messageId ? sanitizeMessageForState({ ...m, ...patch } as Message) : m
          )
          return {
            messagesByConversation: {
              ...state.messagesByConversation,
              [conversationId]: normalizeMessages(next),
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
      version: 5,
      migrate: (persistedState: unknown) => {
        const persisted = isRecord(persistedState) ? persistedState : {}
        const state = persisted as Partial<ConversationState>

        const conversations = Array.isArray(state.conversations)
          ? state.conversations.filter((c) => c && c.type !== 'chat')
          : []
        const allowedIds = new Set(conversations.map((c) => c.id))

        const rawMessages = isRecord(state.messagesByConversation) ? state.messagesByConversation : {}
        const messagesByConversation: Record<string, Message[]> = {}
        for (const [id, messages] of Object.entries(rawMessages)) {
          if (!allowedIds.has(id)) continue
          if (Array.isArray(messages)) messagesByConversation[id] = normalizeMessages(messages as Message[])
        }

        // Back-compat: older builds reused `lesson_plan` for “自学资料”。
        const migratedConversations = conversations.map((c) => {
          if (!c || c.type !== 'lesson_plan') return c
          const msgs = messagesByConversation[c.id] || EMPTY_MESSAGES
          const isStudyMaterials =
            c.activeStream?.taskType === 'study_materials' ||
            (typeof c.title === 'string' && c.title.includes('新自学资料')) ||
            msgs.some((m) => typeof m?.content === 'string' && m.content.includes('已生成自学资料'))
          return isStudyMaterials ? ({ ...c, type: 'study_materials' } as ConversationItem) : c
        })

        const idToType = new Map<string, LocalConversationType>()
        for (const c of migratedConversations) {
          if (c && c.type !== 'chat') idToType.set(c.id, c.type as LocalConversationType)
        }

        const currentConversationIdByType: Record<LocalConversationType, string | null> = {
          ...DEFAULT_CURRENT_BY_TYPE,
        }

        // Newer builds persist per-type selection.
        const rawByType = state.currentConversationIdByType
        if (isRecord(rawByType)) {
          for (const key of Object.keys(DEFAULT_CURRENT_BY_TYPE) as LocalConversationType[]) {
            const val = rawByType[key]
            if (typeof val !== 'string' || !allowedIds.has(val)) continue
            if (idToType.get(val) !== key) continue
            currentConversationIdByType[key] = val
          }
        }

        // Back-compat: older builds stored a single `currentConversationId`.
        const legacyCurrentId = persisted.currentConversationId
        if (typeof legacyCurrentId === 'string' && allowedIds.has(legacyCurrentId)) {
          const t = idToType.get(legacyCurrentId)
          if (t) currentConversationIdByType[t] = legacyCurrentId
        }

        const rawFilter = persisted.filter
        const filter: ConversationState['filter'] =
          rawFilter === 'chat' ||
          rawFilter === 'blueprint' ||
          rawFilter === 'lesson_plan' ||
          rawFilter === 'study_materials' ||
          rawFilter === 'all'
            ? rawFilter
            : 'all'

        return {
          ...state,
          conversations: migratedConversations,
          currentConversationIdByType,
          messagesByConversation,
          filter,
        } as ConversationState
      },
      partialize: (state) => {
        const conversations = (state.conversations || [])
          .filter((c) => c.type !== 'chat')
          .slice(0, MAX_CONVERSATIONS)
        const allowedIds = new Set(conversations.map((c) => c.id))
        const messagesByConversation = Object.fromEntries(
          Object.entries(state.messagesByConversation || {})
            .filter(([id]) => allowedIds.has(id))
            .map(([id, messages]) => [id, sanitizeMessagesForPersist(trimMessages(messages))])
        ) as Record<string, Message[]>

        return {
          conversations,
          currentConversationIdByType: state.currentConversationIdByType,
          filter: state.filter,
          messagesByConversation,
        }
      },
    }
  )
)
