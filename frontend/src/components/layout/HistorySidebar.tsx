import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  MessagesSquare,
  LayoutTemplate,
  BookOpenCheck,
  ChevronRight,
  Trash2,
  Play,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { useConversationStore } from '@/stores/useConversationStore'
import { cn, groupByDate, generateId } from '@/lib/utils'
import type { ConversationItem, ConversationType } from '@/types'

const typeIcons: Record<ConversationType, typeof MessagesSquare> = {
  chat: MessagesSquare,
  blueprint: LayoutTemplate,
  lesson_plan: BookOpenCheck,
}

const typeLabels: Record<ConversationType, string> = {
  chat: '对话',
  blueprint: '蓝图',
  lesson_plan: '自学资料',
}

interface ConversationItemProps {
  item: ConversationItem
  isActive: boolean
  onDelete: (id: string) => void
  onResume: (id: string) => void
}

function ConversationListItem({
  item,
  isActive,
  onDelete,
  onResume,
}: ConversationItemProps) {
  const [showActions, setShowActions] = useState(false)
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

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -10 }}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
      onClick={handleClick}
      className={cn(
        "group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors",
        isActive
          ? "bg-accent text-accent-foreground"
          : "hover:bg-accent/50"
      )}
    >
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />
      
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm truncate">{item.title}</span>
          {item.status === 'paused' && (
            <Badge variant="warning" className="text-xs px-1 py-0">
              暂停
            </Badge>
          )}
        </div>
        
        {/* Progress bar for resumable tasks */}
        {item.resumable && item.progress !== undefined && item.progress < 100 && (
          <div className="mt-1 h-1 w-full bg-muted rounded-full overflow-hidden">
            <div
              className="h-full bg-foreground/70 transition-all"
              style={{ width: `${item.progress}%` }}
            />
          </div>
        )}
      </div>

      {/* Actions */}
      <AnimatePresence>
        {showActions && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex items-center gap-1"
            onClick={(e) => e.stopPropagation()}
          >
            {item.status === 'paused' && item.resumable && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => onResume(item.id)}
              >
                <Play className="h-3 w-3" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-muted-foreground hover:text-destructive"
              onClick={() => onDelete(item.id)}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

export function HistorySidebar() {
  const navigate = useNavigate()
  const {
    conversations,
    currentConversationId,
    filter,
    setFilter,
    addConversation,
    removeConversation,
    setCurrentConversation,
  } = useConversationStore()
  
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    new Set(['今天', '昨天'])
  )

  // Filter conversations
  const filteredConversations = filter === 'all'
    ? conversations
    : conversations.filter((c) => c.type === filter)

  // Group by date
  const groupedConversations = groupByDate(filteredConversations)

  const handleNewConversation = () => {
    const newConversation: ConversationItem = {
      id: generateId(),
      title: '新对话',
      type: 'chat',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      status: 'active',
      resumable: false,
    }
    addConversation(newConversation)
    setCurrentConversation(newConversation.id)
    navigate(`/chat/${newConversation.id}`)
  }

  const handleDelete = (id: string) => {
    removeConversation(id)
  }

  const handleResume = (id: string) => {
    // Will be implemented with task resumption logic
    console.log('Resume task:', id)
  }

  const toggleGroup = (group: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(group)) {
        next.delete(group)
      } else {
        next.add(group)
      }
      return next
    })
  }

  return (
    <aside className="w-64 border-r border-border glass glass-border flex flex-col">
      {/* New conversation button */}
      <div className="p-3">
        <Button
          onClick={handleNewConversation}
          className="w-full justify-start gap-2"
          variant="outline"
        >
          <Plus className="h-4 w-4" />
          新建对话
        </Button>
      </div>

      {/* Filter tabs */}
      <div className="px-3 pb-2 flex gap-1">
        {(['all', 'chat', 'blueprint', 'lesson_plan'] as const).map((type) => (
          <Button
            key={type}
            variant={filter === type ? 'secondary' : 'ghost'}
            size="sm"
            className="text-xs px-2 h-7"
            onClick={() => setFilter(type)}
          >
            {type === 'all' ? '全部' : typeLabels[type]}
          </Button>
        ))}
      </div>

      <Separator />

      {/* Conversation list */}
      <ScrollArea className="flex-1">
        <div className="p-2">
          {Array.from(groupedConversations.entries()).map(([group, items]) => (
            <Collapsible
              key={group}
              open={expandedGroups.has(group)}
              onOpenChange={() => toggleGroup(group)}
            >
              <CollapsibleTrigger asChild>
                <Button
                  variant="ghost"
                  className="w-full justify-between px-2 h-8 text-xs text-muted-foreground hover:text-foreground"
                >
                  {group}
                  <ChevronRight
                    className={cn(
                      "h-4 w-4 transition-transform",
                      expandedGroups.has(group) && "rotate-90"
                    )}
                  />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <AnimatePresence>
                  {items.map((item) => (
                    <ConversationListItem
                      key={item.id}
                      item={item}
                      isActive={currentConversationId === item.id}
                      onDelete={handleDelete}
                      onResume={handleResume}
                    />
                  ))}
                </AnimatePresence>
              </CollapsibleContent>
            </Collapsible>
          ))}

          {filteredConversations.length === 0 && (
            <div className="text-center text-muted-foreground text-sm py-8">
              暂无历史记录
            </div>
          )}
        </div>
      </ScrollArea>
    </aside>
  )
}
