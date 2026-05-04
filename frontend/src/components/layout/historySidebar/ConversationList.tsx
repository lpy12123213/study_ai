import { MoreHorizontal, Pin, Play, Star, Tag, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import type { ConversationItem } from '@/types'
import type { ItemMeta } from '@/api/meta'
import { useI18n } from '@/i18n'
import { metaKey, typeIcons } from './utils'

type ConversationAction = (item: ConversationItem) => void

type ConversationListItemProps = {
  item: ConversationItem
  meta?: ItemMeta
  isActive: boolean
  isCollapsed: boolean
  onDelete: ConversationAction
  onEditTags: ConversationAction
  onOpen: ConversationAction
  onResume: (id: string) => void
  onTogglePin: ConversationAction
  onToggleStar: ConversationAction
}

function ConversationListItem({
  item,
  meta,
  isActive,
  isCollapsed,
  onDelete,
  onEditTags,
  onOpen,
  onResume,
  onTogglePin,
  onToggleStar,
}: ConversationListItemProps) {
  const { t } = useI18n()
  const Icon = typeIcons[item.type]
  const tags = Array.isArray(meta?.tags) ? meta.tags : []
  const isStarred = Boolean(meta?.starred)
  const isPinned = Boolean(meta?.pinned)

  if (isCollapsed) {
    return (
      <button
        type="button"
        onClick={() => onOpen(item)}
        className={cn(
          'mb-1 flex cursor-pointer justify-center rounded-md py-2 transition-colors',
          isActive
            ? 'bg-sidebar-primary text-sidebar-primary-foreground'
            : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
        )}
        title={item.title}
        aria-label={t('history.openItem', { title: item.title })}
      >
        <Icon className="h-4 w-4" />
      </button>
    )
  }

  return (
    <div
      className={cn(
        'group mb-0.5 flex items-center gap-2 rounded-md border border-transparent px-2 py-1.5 text-sm transition-colors',
        isActive
          ? 'border-sidebar-border bg-sidebar-accent text-sidebar-accent-foreground font-medium'
          : 'text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
      )}
    >
      <button
        type="button"
        onClick={() => onOpen(item)}
        className="flex items-center gap-2 flex-1 min-w-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-md"
      >
        <Icon className="h-4 w-4 shrink-0 opacity-70" />
        {isPinned && <Pin className="h-3.5 w-3.5 shrink-0 opacity-70" />}
        {isStarred && <Star className="h-3.5 w-3.5 shrink-0 opacity-70" />}
        <span className="truncate flex-1">{item.title}</span>
        {tags.slice(0, 2).map((tag) => (
          <span key={tag} className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {tag}
          </span>
        ))}
      </button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
            aria-label={t('history.moreActions')}
          >
            <MoreHorizontal className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => onToggleStar(item)}>
            <Star className="mr-2 h-3 w-3" />
            {isStarred ? t('history.unfavorite') : t('history.favorite')}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onTogglePin(item)}>
            <Pin className="mr-2 h-3 w-3" />
            {isPinned ? t('history.unpin') : t('history.pin')}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onEditTags(item)}>
            <Tag className="mr-2 h-3 w-3" />
            {t('history.setTags')}
          </DropdownMenuItem>
          {item.status === 'paused' && item.resumable && (
            <DropdownMenuItem onClick={() => onResume(item.id)}>
              <Play className="mr-2 h-3 w-3" />
              {t('history.resumeTask')}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={() => onDelete(item)} className="text-destructive focus:text-destructive">
            <Trash2 className="mr-2 h-3 w-3" />
            {t('history.delete')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

type ConversationListProps = {
  effectiveActiveId: string | null
  filteredConversations: ConversationItem[]
  groupedConversations: Map<string, ConversationItem[]>
  isCollapsed: boolean
  metaByKey: Map<string, ItemMeta>
  pinnedConversations: ConversationItem[]
  onDelete: ConversationAction
  onEditTags: ConversationAction
  onOpen: ConversationAction
  onResume: (id: string) => void
  onTogglePin: ConversationAction
  onToggleStar: ConversationAction
}

export function ConversationList({
  effectiveActiveId,
  filteredConversations,
  groupedConversations,
  isCollapsed,
  metaByKey,
  pinnedConversations,
  onDelete,
  onEditTags,
  onOpen,
  onResume,
  onTogglePin,
  onToggleStar,
}: ConversationListProps) {
  const { t } = useI18n()
  const groupLabel = (group: string) => {
    if (group === '今天') return t('history.groupToday')
    if (group === '昨天') return t('history.groupYesterday')
    if (group === '本周') return t('history.groupThisWeek')
    if (group === '更早') return t('history.groupOlder')
    return group
  }

  const renderItem = (item: ConversationItem) => (
    <ConversationListItem
      key={metaKey(item.type, item.id)}
      item={item}
      meta={metaByKey.get(metaKey(item.type, item.id))}
      isActive={effectiveActiveId === item.id}
      onDelete={onDelete}
      onEditTags={onEditTags}
      onOpen={onOpen}
      onResume={onResume}
      onTogglePin={onTogglePin}
      onToggleStar={onToggleStar}
      isCollapsed={isCollapsed}
    />
  )

  return (
    <>
      {pinnedConversations.length > 0 && (
        <div className="mb-4">
          {!isCollapsed && <div className="px-2 mb-1 text-xs font-medium text-muted-foreground/70">{t('history.pinned')}</div>}
          <div className="space-y-0.5">{pinnedConversations.map(renderItem)}</div>
        </div>
      )}

      {Array.from(groupedConversations.entries()).map(([group, items]) => (
        <div key={group} className="mb-4">
          {!isCollapsed && <h3 className="px-2 mb-1 text-xs font-medium text-muted-foreground/70">{groupLabel(group)}</h3>}
          <div className="space-y-0.5">{items.map(renderItem)}</div>
        </div>
      ))}

      {filteredConversations.length === 0 && !isCollapsed && (
        <div className="text-center text-muted-foreground text-xs py-8">{t('history.empty')}</div>
      )}
    </>
  )
}
