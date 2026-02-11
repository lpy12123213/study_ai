import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Plus,
  MessagesSquare,
  LayoutTemplate,
  BookOpenCheck,
  Search,
  MoreHorizontal,
  Trash2,
  Play,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
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
import type { ConversationItem, ConversationType } from '@/types'

const typeIcons: Record<ConversationType, typeof MessagesSquare> = {
  chat: MessagesSquare,
  blueprint: LayoutTemplate,
  lesson_plan: BookOpenCheck,
}

interface ConversationItemProps {
  item: ConversationItem
  isActive: boolean
  onDelete: (item: ConversationItem) => void
  onResume: (id: string) => void
  isCollapsed: boolean
}

function ConversationListItem({
  item,
  isActive,
  onDelete,
  onResume,
  isCollapsed,
}: ConversationItemProps) {
  const Icon = typeIcons[item.type]
  const navigate = useNavigate()
  const setCurrentConversation = useConversationStore(
    (state) => state.setCurrentConversation
  )

  const handleClick = () => {
    setCurrentConversation(item.id)
    if (item.type === 'chat') {
      navigate(`/chat/${item.id}`)
      return
    }
    if (item.type === 'blueprint') {
      navigate('/blueprint')
      return
    }
    navigate('/study-materials')
  }

  if (isCollapsed) {
    return (
      <div
        onClick={handleClick}
        className={cn(
          "flex justify-center py-2 rounded-md cursor-pointer transition-colors mb-1",
          isActive
            ? "bg-accent text-accent-foreground"
            : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
        )}
        title={item.title}
      >
        <Icon className="h-4 w-4" />
      </div>
    )
  }

  return (
    <div
      onClick={handleClick}
      className={cn(
        "group flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors text-sm mb-0.5",
        isActive
          ? "bg-accent text-accent-foreground font-medium"
          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
      )}
    >
      <Icon className="h-4 w-4 shrink-0 opacity-70" />
      <span className="truncate flex-1">{item.title}</span>
      
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
            onClick={(e) => e.stopPropagation()}
          >
            <MoreHorizontal className="h-3 w-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
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
    currentConversationId,
    removeConversation,
    setCurrentConversation,
  } = useConversationStore()
  
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  const { data: chatConversations = [] } = useQuery({
    queryKey: ['chatConversations'],
    queryFn: () => chatApi.getConversations(100),
    enabled: isAuthenticated && Boolean(token),
  })

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

  const effectiveChatConversations =
    isAuthenticated && token ? chatConversations : ([] as ConversationItem[])

  const conversations: ConversationItem[] = [...effectiveChatConversations, ...localConversations]

  // Filter conversations
  const filteredConversations = conversations.filter((c) => 
    c.title.toLowerCase().includes(searchQuery.toLowerCase())
  )

  // Group by date
  const groupedConversations = groupByDate(filteredConversations)

  const handleNewConversation = () => {
    // Route `/chat` will create a new backend conversation lazily on first message.
    setCurrentConversation(null)
    navigate('/chat')
  }

  const activeChatId = (() => {
    const m = location.pathname.match(/^\/chat\/([^/?#]+)/)
    return m ? m[1] : null
  })()

  const effectiveActiveId = activeChatId || currentConversationId

  const handleDeleteConversation = (item: ConversationItem) => {
    if (item.type === 'chat') {
      deleteChatConversation.mutate(item.id)
      if (effectiveActiveId === item.id) {
        setCurrentConversation(null)
        navigate('/chat')
      }
      return
    }
    removeConversation(item.id)
  }

  return (
    <motion.aside 
      initial={false}
      animate={{ width: isCollapsed ? 60 : 260 }}
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
          >
            <Plus className="h-4 w-4" />
          </Button>
        )}
        
        <Button
          variant="ghost"
          size="icon"
          className={cn("h-8 w-8 text-muted-foreground", !isCollapsed && "ml-2")}
          onClick={() => setIsCollapsed(!isCollapsed)}
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
        </div>
      )}

      <ScrollArea className="flex-1">
        <div className="p-2">
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
                    isActive={effectiveActiveId === item.id}
                    onDelete={handleDeleteConversation}
                    onResume={() => {}}
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
