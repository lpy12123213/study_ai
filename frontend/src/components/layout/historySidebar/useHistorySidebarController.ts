import { useCallback, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MEDIA_QUERIES } from '@/lib/breakpoints'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { useLayoutPrefs } from '@/hooks/useLayoutPrefs'
import { useRunningTasks } from '@/hooks/useRunningTasks'
import { useAuthStore } from '@/stores/useAuthStore'
import { useConversationStore } from '@/stores/useConversationStore'
import * as chatApi from '@/api/chat'
import * as metaApi from '@/api/meta'
import type { ConversationItem, ConversationType } from '@/types'
import { conversationTarget, getPageTypeFilter, metaKey, newConversationTarget, parseTagsInput } from './utils'
import { useConversationFilter } from './useConversationFilter'

type MetaPatch = { starred?: boolean; pinned?: boolean; tags?: string[] }
type LocalConversationType = Exclude<ConversationType, 'chat'>

export function useHistorySidebarController() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { isAuthenticated, token } = useAuthStore()
  const { sidebarStyle, sidebarPosition, sidebarCollapsed: isCollapsed, setSidebarCollapsed } = useLayoutPrefs()
  const { currentConversationIdByType, removeConversation, setCurrentConversation } = useConversationStore()
  const storedConversations = useConversationStore((state) => state.conversations)
  const isMobile = useMediaQuery(MEDIA_QUERIES.mobile)
  const [searchQuery, setSearchQuery] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [tagEditorItem, setTagEditorItem] = useState<ConversationItem | null>(null)
  const [tagEditorValue, setTagEditorValue] = useState('')

  const pageTypeFilter = useMemo(() => getPageTypeFilter(location.pathname), [location.pathname])

  const { data: chatConversations = [] } = useQuery({
    queryKey: ['chatConversations'],
    queryFn: () => chatApi.getConversations(100),
    enabled: isAuthenticated && Boolean(token),
  })

  const { data: runningTasksResp } = useRunningTasks({ enabled: isAuthenticated && Boolean(token) })
  const runningTasks = runningTasksResp?.tasks || []

  const deleteChatConversation = useMutation({
    mutationFn: chatApi.deleteConversation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chatConversations'] })
    },
  })

  const localConversations = useMemo(
    () => (storedConversations || []).filter((conversation) => conversation.type !== 'chat'),
    [storedConversations],
  )

  const effectiveChatConversations = useMemo<ConversationItem[]>(
    () => (isAuthenticated && token ? chatConversations : []),
    [chatConversations, isAuthenticated, token],
  )

  const conversations = useMemo(
    () => [...effectiveChatConversations, ...localConversations],
    [effectiveChatConversations, localConversations],
  )

  const { data: metaResp } = useQuery({
    queryKey: ['itemMeta', pageTypeFilter],
    queryFn: () => metaApi.listMeta({ itemType: pageTypeFilter || undefined, limit: 500 }),
    enabled: isAuthenticated && Boolean(token),
    staleTime: 30_000,
  })

  const {
    filteredConversations,
    groupedConversations,
    metaByKey,
    pinnedConversations,
    tagOptions,
  } = useConversationFilter({
    conversations,
    metaItems: metaResp?.items || [],
    pageTypeFilter,
    searchQuery,
    tagFilter,
    setTagFilter,
  })

  const updateMeta = useMutation({
    mutationFn: (args: { itemType: string; itemId: string; patch: MetaPatch }) =>
      metaApi.setMeta(args.itemType, args.itemId, args.patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['itemMeta', pageTypeFilter] })
    },
  })

  const activeChatId = useMemo(() => {
    const match = location.pathname.match(/^\/chat\/([^/?#]+)/)
    return match ? match[1] : null
  }, [location.pathname])

  const activeLocalId =
    pageTypeFilter && pageTypeFilter !== 'chat'
      ? currentConversationIdByType[pageTypeFilter as LocalConversationType]
      : null
  const effectiveActiveId = activeChatId || activeLocalId

  const openConversation = useCallback(
    (item: ConversationItem) => {
      if (item.type !== 'chat') {
        setCurrentConversation(item.id, item.type)
      }
      navigate(conversationTarget(item))
    },
    [navigate, setCurrentConversation],
  )

  const applyMetaPatch = useCallback(
    (item: ConversationItem, patch: MetaPatch) => {
      updateMeta.mutate({ itemType: item.type, itemId: String(item.id), patch })
    },
    [updateMeta],
  )

  const handleToggleStar = useCallback(
    (item: ConversationItem) => {
      const meta = metaByKey.get(metaKey(item.type, item.id))
      applyMetaPatch(item, { starred: !meta?.starred })
    },
    [applyMetaPatch, metaByKey],
  )

  const handleTogglePin = useCallback(
    (item: ConversationItem) => {
      const meta = metaByKey.get(metaKey(item.type, item.id))
      applyMetaPatch(item, { pinned: !meta?.pinned })
    },
    [applyMetaPatch, metaByKey],
  )

  const handleEditTags = useCallback(
    (item: ConversationItem) => {
      const meta = metaByKey.get(metaKey(item.type, item.id))
      setTagEditorItem(item)
      setTagEditorValue((meta?.tags || []).join(', '))
    },
    [metaByKey],
  )

  const handleSaveTags = useCallback(() => {
    if (!tagEditorItem) return
    applyMetaPatch(tagEditorItem, { tags: parseTagsInput(tagEditorValue) })
    setTagEditorItem(null)
    setTagEditorValue('')
  }, [applyMetaPatch, tagEditorItem, tagEditorValue])

  const handleResumeConversation = useCallback(
    (id: string) => {
      const item = conversations.find((conversation) => conversation.id === id)
      if (item) openConversation(item)
    },
    [conversations, openConversation],
  )

  const handleNewConversation = useCallback(() => {
    if (pageTypeFilter && pageTypeFilter !== 'chat') {
      setCurrentConversation(null, pageTypeFilter)
    }
    navigate(newConversationTarget(location.pathname))
  }, [location.pathname, navigate, pageTypeFilter, setCurrentConversation])

  const handleDeleteConversation = useCallback(
    (item: ConversationItem) => {
      if (item.type === 'chat') {
        deleteChatConversation.mutate(item.id)
        if (effectiveActiveId === item.id) navigate('/chat')
        return
      }
      removeConversation(item.id)
    },
    [deleteChatConversation, effectiveActiveId, navigate, removeConversation],
  )

  const handleOpenSearch = useCallback(() => {
    navigate('/search')
  }, [navigate])

  const handleOpenTaskCenter = useCallback(() => {
    navigate('/tasks')
  }, [navigate])

  const handleOpenTask = useCallback(
    (taskId: string) => {
      navigate(`/tasks?id=${encodeURIComponent(taskId)}`)
    },
    [navigate],
  )

  return {
    collapsedWidth: isMobile ? 52 : 60,
    effectiveActiveId,
    expandedWidth: sidebarStyle === 'floating' ? 280 : 260,
    filteredConversations,
    groupedConversations,
    handleDeleteConversation,
    handleEditTags,
    handleNewConversation,
    handleOpenSearch,
    handleOpenTask,
    handleOpenTaskCenter,
    handleResumeConversation,
    handleSaveTags,
    handleTogglePin,
    handleToggleStar,
    isAuthenticated,
    isCollapsed,
    metaByKey,
    openConversation,
    pinnedConversations,
    runningTasks,
    searchQuery,
    setSearchQuery,
    setSidebarCollapsed,
    setTagEditorItem,
    setTagEditorValue,
    setTagFilter,
    sidebarPosition,
    sidebarStyle,
    tagEditorItem,
    tagEditorValue,
    tagFilter,
    tagOptions,
  }
}
