import { useMemo, useState, useCallback, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Plus,
  MessagesSquare,
  LayoutTemplate,
  BookOpen,
  BookOpenCheck,
  Search,
  Star,
  Pin,
  Tag,
  MoreHorizontal,
  Trash2,
  Play,
  PanelLeftClose,
  PanelLeftOpen,
  ListChecks,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useConversationStore } from '@/stores/useConversationStore'
import { useAuthStore } from '@/stores/useAuthStore'
import { cn, groupByDate } from '@/lib/utils'
import * as chatApi from '@/api/chat'
import * as tasksApi from '@/api/tasks'
import * as metaApi from '@/api/meta'
import type { ConversationItem, ConversationType } from '@/types'

const typeIcons: Record<ConversationType, typeof MessagesSquare> = {
  chat: MessagesSquare,
  blueprint: LayoutTemplate,
  lesson_plan: BookOpenCheck,
  study_materials: BookOpen,
}

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'manus.sidebar.collapsed'
const MOBILE_MEDIA_QUERY = '(max-width: 1023px)'

interface ConversationItemProps {
  item: ConversationItem
  meta?: metaApi.ItemMeta
  isActive: boolean
  onDelete: (item: ConversationItem) => void
  onResume: (id: string) => void
  onToggleStar: (item: ConversationItem) => void
  onTogglePin: (item: ConversationItem) => void
  onEditTags: (item: ConversationItem) => void
  isCollapsed: boolean
}

function ConversationListItem({
  item,
  meta,
  isActive,
  onDelete,
  onResume,
  onToggleStar,
  onTogglePin,
  onEditTags,
  isCollapsed,
}: ConversationItemProps) {
  const Icon = typeIcons[item.type]
  const navigate = useNavigate()
  const setCurrentConversation = useConversationStore(
    (state) => state.setCurrentConversation
  )

  const handleClick = () => {
    if (item.type !== 'chat') {
      setCurrentConversation(item.id, item.type)
    }
    if (item.type === 'chat') {
      navigate(`/chat/${item.id}`)
      return
    }
    if (item.type === 'blueprint') {
      navigate('/blueprint')
      return
    }
    if (item.type === 'lesson_plan') {
      navigate('/lesson-plans')
      return
    }
    navigate('/study-materials')
  }

  if (isCollapsed) {
    return (
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          "flex justify-center py-2 rounded-md cursor-pointer transition-colors mb-1",
          isActive
            ? "bg-accent text-accent-foreground"
            : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
        )}
        title={item.title}
        aria-label={`打开：${item.title}`}
      >
        <Icon className="h-4 w-4" />
      </button>
    )
  }

  const tags = Array.isArray((meta as any)?.tags) ? ((meta as any).tags as string[]) : []
  const isStarred = Boolean((meta as any)?.starred)
  const isPinned = Boolean((meta as any)?.pinned)

  return (
    <div
      className={cn(
        "group flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors text-sm mb-0.5",
        isActive
          ? "bg-accent text-accent-foreground font-medium"
          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
      )}
    >
      <button
        type="button"
        onClick={handleClick}
        className="flex items-center gap-2 flex-1 min-w-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-md"
      >
        <Icon className="h-4 w-4 shrink-0 opacity-70" />
        {isPinned && <Pin className="h-3.5 w-3.5 shrink-0 opacity-70" />}
        {isStarred && <Star className="h-3.5 w-3.5 shrink-0 opacity-70" />}
        <span className="truncate flex-1">{item.title}</span>
        {tags.slice(0, 2).map((t) => (
          <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
            {t}
          </span>
        ))}
      </button>
      
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
            aria-label="更多操作"
          >
            <MoreHorizontal className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => onToggleStar(item)}>
            <Star className="mr-2 h-3 w-3" />
            {isStarred ? '取消收藏' : '收藏'}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onTogglePin(item)}>
            <Pin className="mr-2 h-3 w-3" />
            {isPinned ? '取消置顶' : '置顶'}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onEditTags(item)}>
            <Tag className="mr-2 h-3 w-3" />
            设置标签…
          </DropdownMenuItem>
          {item.status === 'paused' && item.resumable && (
            <DropdownMenuItem onClick={() => onResume(item.id)}>
              <Play className="mr-2 h-3 w-3" />
              继续任务
            </DropdownMenuItem>
          )}
          <DropdownMenuItem 
            onClick={() => onDelete(item)}
            className="text-destructive focus:text-destructive"
          >
            <Trash2 className="mr-2 h-3 w-3" />
            删除
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

export function HistorySidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { isAuthenticated, token } = useAuthStore()
  const {
    currentConversationIdByType,
    removeConversation,
    setCurrentConversation,
  } = useConversationStore()
  
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(MOBILE_MEDIA_QUERY).matches
  })
  const [isCollapsed, setIsCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)
    if (stored === 'true') return true
    if (stored === 'false') return false
    return window.matchMedia(MOBILE_MEDIA_QUERY).matches
  })
  const [searchQuery, setSearchQuery] = useState('')
  const [tagFilter, setTagFilter] = useState('')

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, isCollapsed ? 'true' : 'false')
  }, [isCollapsed])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const media = window.matchMedia(MOBILE_MEDIA_QUERY)
    const update = (event?: MediaQueryListEvent) => {
      const nextMobile = event ? event.matches : media.matches
      setIsMobile(nextMobile)
      if (window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) == null) {
        setIsCollapsed(nextMobile)
      }
    }

    update()
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update)
      return () => media.removeEventListener('change', update)
    }

    media.addListener(update)
    return () => media.removeListener(update)
  }, [])

  const { data: chatConversations = [] } = useQuery({
    queryKey: ['chatConversations'],
    queryFn: () => chatApi.getConversations(100),
    enabled: isAuthenticated && Boolean(token),
  })

  const { data: runningTasksResp } = useQuery({
    queryKey: ['runningTasks'],
    queryFn: () => tasksApi.listTasks({ status: 'running', limit: 8 }),
    enabled: isAuthenticated && Boolean(token),
    refetchInterval: 5000,
  })

  const runningTasks = runningTasksResp?.tasks || []

  const deleteChatConversation = useMutation({
    mutationFn: chatApi.deleteConversation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chatConversations'] })
    },
  })

  const storedConversations = useConversationStore((state) => state.conversations)
  const localConversations = useMemo(
    () => (storedConversations || []).filter((c) => c.type !== 'chat'),
    [storedConversations]
  )

  const effectiveChatConversations = useMemo<ConversationItem[]>(
    () => (isAuthenticated && token ? chatConversations : []),
    [isAuthenticated, token, chatConversations]
  )

  const conversations: ConversationItem[] = useMemo(
    () => [...effectiveChatConversations, ...localConversations],
    [effectiveChatConversations, localConversations]
  )

  // Scope conversations to the current page so different features don't mix
  const pageTypeFilter: ConversationType | null = (() => {
    if (location.pathname.startsWith('/study-materials')) return 'study_materials'
    if (location.pathname.startsWith('/lesson-plans')) return 'lesson_plan'
    if (location.pathname.startsWith('/chat')) return 'chat'
    if (location.pathname.startsWith('/blueprint')) return 'blueprint'
    return null
  })()

  const { data: metaResp } = useQuery({
    queryKey: ['itemMeta', pageTypeFilter],
    queryFn: () => metaApi.listMeta({ itemType: pageTypeFilter || undefined, limit: 500 }),
    enabled: isAuthenticated && Boolean(token),
    staleTime: 30_000,
  })

  const metaItems = (metaResp as any)?.items || []

  const metaByKey = useMemo(() => {
    const m = new Map<string, metaApi.ItemMeta>()
    for (const row of metaItems as metaApi.ItemMeta[]) {
      const k = `${String((row as any).item_type)}:${String((row as any).item_id)}`
      m.set(k, row)
    }
    return m
  }, [metaItems])

  const tagOptions = useMemo(() => {
    const set = new Set<string>()
    for (const row of metaItems as metaApi.ItemMeta[]) {
      const t = String((row as any).item_type || '')
      if (pageTypeFilter && t !== pageTypeFilter) continue
      const tags = Array.isArray((row as any).tags) ? ((row as any).tags as string[]) : []
      for (const tag of tags) {
        const v = String(tag || '').trim()
        if (v) set.add(v)
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  }, [metaItems, pageTypeFilter])

  useEffect(() => {
    if (!tagFilter) return
    if (tagOptions.includes(tagFilter)) return
    setTagFilter('')
  }, [tagFilter, tagOptions])

  // Filter conversations
  const filteredConversations = conversations.filter((c) => {
    if (pageTypeFilter && c.type !== pageTypeFilter) return false
    const meta = metaByKey.get(`${c.type}:${c.id}`)
    if (tagFilter && !(meta?.tags || []).includes(tagFilter)) return false

    const q = searchQuery.trim().toLowerCase()
    if (!q) return true
    const inTitle = c.title.toLowerCase().includes(q)
    const inTags = (meta?.tags || []).some((t) => String(t || '').toLowerCase().includes(q))
    return inTitle || inTags
  })

  const pinnedConversations = useMemo(
    () => filteredConversations.filter((c) => metaByKey.get(`${c.type}:${c.id}`)?.pinned),
    [filteredConversations, metaByKey],
  )

  const unpinnedConversations = useMemo(
    () => filteredConversations.filter((c) => !metaByKey.get(`${c.type}:${c.id}`)?.pinned),
    [filteredConversations, metaByKey],
  )

  // Group by date
  const groupedConversations = groupByDate(unpinnedConversations)

  const updateMeta = useMutation({
    mutationFn: (args: { itemType: string; itemId: string; patch: { starred?: boolean; pinned?: boolean; tags?: string[] } }) =>
      metaApi.setMeta(args.itemType, args.itemId, args.patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['itemMeta', pageTypeFilter] })
    },
  })

  const applyMetaPatch = (item: ConversationItem, patch: { starred?: boolean; pinned?: boolean; tags?: string[] }) => {
    updateMeta.mutate({ itemType: item.type, itemId: String(item.id), patch })
  }

  const handleToggleStar = (item: ConversationItem) => {
    const meta = metaByKey.get(`${item.type}:${item.id}`)
    applyMetaPatch(item, { starred: !meta?.starred })
  }

  const handleTogglePin = (item: ConversationItem) => {
    const meta = metaByKey.get(`${item.type}:${item.id}`)
    applyMetaPatch(item, { pinned: !meta?.pinned })
  }

  const handleEditTags = (item: ConversationItem) => {
    const meta = metaByKey.get(`${item.type}:${item.id}`)
    const current = (meta?.tags || []).join(', ')
    const raw = window.prompt('标签（逗号分隔）', current)
    if (raw == null) return
    const tags = raw
      .split(',')
      .map((t) => t.trim())
      .filter((t) => t.length > 0)
      .slice(0, 20)
    applyMetaPatch(item, { tags })
  }

  const handleResumeConversation = useCallback(
    (id: string) => {
      const item = conversations.find((c) => c.id === id)
      if (!item) return

      if (item.type !== 'chat') {
        setCurrentConversation(item.id, item.type)
      }
      if (item.type === 'chat') {
        navigate(`/chat/${item.id}`)
        return
      }
      if (item.type === 'blueprint') {
        navigate('/blueprint')
        return
      }
      if (item.type === 'lesson_plan') {
        navigate('/lesson-plans')
        return
      }
      navigate('/study-materials')
    },
    [conversations, navigate, setCurrentConversation]
  )

  const handleNewConversation = () => {
    if (pageTypeFilter && pageTypeFilter !== 'chat') {
      setCurrentConversation(null, pageTypeFilter)
    }
    if (location.pathname.startsWith('/study-materials')) {
      navigate('/study-materials')
    } else if (location.pathname.startsWith('/lesson-plans')) {
      navigate('/lesson-plans')
    } else if (location.pathname.startsWith('/blueprint')) {
      navigate('/blueprint')
    } else {
      navigate('/chat')
    }
  }

  const activeChatId = (() => {
    const m = location.pathname.match(/^\/chat\/([^/?#]+)/)
    return m ? m[1] : null
  })()

  const activeLocalId =
    pageTypeFilter && pageTypeFilter !== 'chat' ? currentConversationIdByType[pageTypeFilter] : null

  const effectiveActiveId = activeChatId || activeLocalId

  const handleDeleteConversation = (item: ConversationItem) => {
    if (item.type === 'chat') {
      deleteChatConversation.mutate(item.id)
      if (effectiveActiveId === item.id) {
        navigate('/chat')
      }
      return
    }
    removeConversation(item.id)
  }

  return (
    <motion.aside 
      initial={false}
      animate={{ width: isCollapsed ? (isMobile ? 52 : 60) : 260 }}
      className="border-r border-border bg-sidebar-background flex flex-col relative transition-all duration-300 ease-in-out"
    >
      <div className="p-3 flex items-center justify-between">
        {!isCollapsed && (
          <Button
            onClick={handleNewConversation}
            className="flex-1 justify-start gap-2 bg-sidebar-primary text-sidebar-primary-foreground hover:bg-sidebar-primary/90 shadow-none"
            size="sm"
          >
            <Plus className="h-4 w-4" />
            新建对话
          </Button>
        )}
         {isCollapsed && (
            <Button
             onClick={handleNewConversation}
             size="icon"
             variant="ghost"
             className="mx-auto h-8 w-8"
             aria-label="新建对话"
           >
             <Plus className="h-4 w-4" />
           </Button>
         )}
         
        <Button
         variant="ghost"
         size="icon"
         className={cn("h-8 w-8 text-muted-foreground", !isCollapsed && "ml-2")}
         onClick={() => setIsCollapsed(!isCollapsed)}
         aria-label={isCollapsed ? '展开侧边栏' : '收起侧边栏'}
       >
          {isCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </Button>
      </div>

      {!isCollapsed && (
        <div className="px-3 pb-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input 
              placeholder="搜索..." 
              className="h-8 pl-8 bg-sidebar-accent/50 border-sidebar-border focus-visible:ring-sidebar-ring"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          {tagOptions.length > 0 && (
            <div className="mt-2 flex items-center gap-2">
              <Tag className="h-3.5 w-3.5 text-muted-foreground" />
              <select
                className="h-8 rounded-md border border-sidebar-border bg-sidebar-accent/50 px-2 text-xs flex-1"
                value={tagFilter}
                onChange={(e) => setTagFilter(e.target.value)}
              >
                <option value="">全部标签</option>
                {tagOptions.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          )}

          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-2 w-full justify-start gap-2 text-muted-foreground hover:text-foreground"
            onClick={() => navigate('/search')}
          >
            <Search className="h-4 w-4" />
            全文搜索
          </Button>
        </div>
      )}

      <ScrollArea className="flex-1">
        <div className="p-2">
          {/* Global tasks section */}
          {isAuthenticated && (
            <div className="mb-4">
              {!isCollapsed && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start gap-2"
                  onClick={() => navigate('/tasks')}
                >
                  <ListChecks className="h-4 w-4" />
                  任务中心
                  {runningTasks.length > 0 && (
                    <Badge variant="secondary" className="ml-auto">
                      {runningTasks.length}
                    </Badge>
                  )}
                </Button>
              )}
              {isCollapsed && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="mx-auto h-8 w-8 relative"
                  onClick={() => navigate('/tasks')}
                  aria-label="任务中心"
                  title="任务中心"
                >
                  <ListChecks className="h-4 w-4" />
                  {runningTasks.length > 0 && (
                    <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-primary" />
                  )}
                </Button>
              )}

              {!isCollapsed && runningTasks.length > 0 && (
                <div className="mt-2 space-y-1">
                  <div className="px-2 text-xs font-medium text-muted-foreground/70">运行中</div>
                  {runningTasks.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => navigate(`/tasks?id=${encodeURIComponent(t.id)}`)}
                      className="w-full flex items-center justify-between gap-2 px-2 py-1 rounded-md text-xs text-muted-foreground hover:bg-accent/50 hover:text-foreground transition-colors"
                      title={t.title}
                      aria-label={`打开任务：${t.title}`}
                    >
                      <span className="truncate">{t.title}</span>
                      <span className="shrink-0">{Math.round(Number(t.progress || 0))}%</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {pinnedConversations.length > 0 && (
            <div className="mb-4">
              {!isCollapsed && <div className="px-2 mb-1 text-xs font-medium text-muted-foreground/70">置顶</div>}
              <div className="space-y-0.5">
                {pinnedConversations.map((item) => (
                  <ConversationListItem
                    key={`${item.type}:${item.id}`}
                    item={item}
                    meta={metaByKey.get(`${item.type}:${item.id}`)}
                    isActive={effectiveActiveId === item.id}
                    onDelete={handleDeleteConversation}
                    onResume={handleResumeConversation}
                    onToggleStar={handleToggleStar}
                    onTogglePin={handleTogglePin}
                    onEditTags={handleEditTags}
                    isCollapsed={isCollapsed}
                  />
                ))}
              </div>
            </div>
          )}

          {Array.from(groupedConversations.entries()).map(([group, items]) => (
            <div key={group} className="mb-4">
              {!isCollapsed && (
                <h3 className="px-2 mb-1 text-xs font-medium text-muted-foreground/70">
                  {group}
                </h3>
              )}
              <div className="space-y-0.5">
                {items.map((item) => (
                  <ConversationListItem
                    key={item.id}
                    item={item}
                    meta={metaByKey.get(`${item.type}:${item.id}`)}
                    isActive={effectiveActiveId === item.id}
                    onDelete={handleDeleteConversation}
                    onResume={handleResumeConversation}
                    onToggleStar={handleToggleStar}
                    onTogglePin={handleTogglePin}
                    onEditTags={handleEditTags}
                    isCollapsed={isCollapsed}
                  />
                ))}
              </div>
            </div>
          ))}

          {filteredConversations.length === 0 && !isCollapsed && (
            <div className="text-center text-muted-foreground text-xs py-8">
              暂无历史记录
            </div>
          )}
        </div>
      </ScrollArea>
    </motion.aside>
  )
}
