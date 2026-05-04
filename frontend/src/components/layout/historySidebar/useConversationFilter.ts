import { useEffect, useMemo } from 'react'
import { groupByDate } from '@/lib/utils'
import type { ConversationItem, ConversationType } from '@/types'
import type { ItemMeta } from '@/api/meta'
import { metaKey } from './utils'

type UseConversationFilterArgs = {
  conversations: ConversationItem[]
  metaItems: ItemMeta[]
  pageTypeFilter: ConversationType | null
  searchQuery: string
  tagFilter: string
  setTagFilter: (value: string) => void
}

export function useConversationFilter({
  conversations,
  metaItems,
  pageTypeFilter,
  searchQuery,
  tagFilter,
  setTagFilter,
}: UseConversationFilterArgs) {
  const metaByKey = useMemo(() => {
    const map = new Map<string, ItemMeta>()
    for (const row of metaItems) {
      map.set(metaKey(row.item_type, row.item_id), row)
    }
    return map
  }, [metaItems])

  const tagOptions = useMemo(() => {
    const set = new Set<string>()
    for (const row of metaItems) {
      if (pageTypeFilter && row.item_type !== pageTypeFilter) continue
      for (const tag of row.tags || []) {
        const value = String(tag || '').trim()
        if (value) set.add(value)
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  }, [metaItems, pageTypeFilter])

  useEffect(() => {
    if (!tagFilter) return
    if (tagOptions.includes(tagFilter)) return
    setTagFilter('')
  }, [setTagFilter, tagFilter, tagOptions])

  const filteredConversations = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    return conversations.filter((conversation) => {
      if (pageTypeFilter && conversation.type !== pageTypeFilter) return false
      const meta = metaByKey.get(metaKey(conversation.type, conversation.id))
      if (tagFilter && !(meta?.tags || []).includes(tagFilter)) return false
      if (!query) return true

      const inTitle = conversation.title.toLowerCase().includes(query)
      const inTags = (meta?.tags || []).some((tag) => String(tag || '').toLowerCase().includes(query))
      return inTitle || inTags
    })
  }, [conversations, metaByKey, pageTypeFilter, searchQuery, tagFilter])

  const pinnedConversations = useMemo(
    () => filteredConversations.filter((conversation) => metaByKey.get(metaKey(conversation.type, conversation.id))?.pinned),
    [filteredConversations, metaByKey],
  )

  const groupedConversations = useMemo(() => {
    const unpinned = filteredConversations.filter(
      (conversation) => !metaByKey.get(metaKey(conversation.type, conversation.id))?.pinned,
    )
    return groupByDate(unpinned)
  }, [filteredConversations, metaByKey])

  return {
    filteredConversations,
    groupedConversations,
    metaByKey,
    pinnedConversations,
    tagOptions,
  }
}
