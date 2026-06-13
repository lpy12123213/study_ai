import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { ConversationList } from './ConversationList'
import { SidebarControls } from './SidebarControls'
import { TagEditDialog } from './TagEditDialog'
import { TaskRail } from './TaskRail'
import { useHistorySidebarController } from './useHistorySidebarController'

export function HistorySidebar() {
  const sidebar = useHistorySidebarController()

  return (
    <aside
      style={{ width: sidebar.isCollapsed ? sidebar.collapsedWidth : sidebar.expandedWidth }}
      className={cn(
        'aurora-history-sidebar aurora-layout-surface relative flex shrink-0 flex-col bg-sidebar-background transition-[width] duration-300 ease-in-out',
        sidebar.sidebarStyle === 'sidebar' &&
          (sidebar.sidebarPosition === 'right' ? 'border-l border-border' : 'border-r border-border'),
        sidebar.sidebarStyle === 'inset' && 'm-2 overflow-hidden rounded-lg border border-border shadow-none',
        sidebar.sidebarStyle === 'floating' &&
          'm-3 overflow-hidden rounded-lg border border-border bg-sidebar-background shadow-none',
      )}
    >
      <SidebarControls
        isCollapsed={sidebar.isCollapsed}
        searchQuery={sidebar.searchQuery}
        tagFilter={sidebar.tagFilter}
        tagOptions={sidebar.tagOptions}
        onNewConversation={sidebar.handleNewConversation}
        onOpenSearch={sidebar.handleOpenSearch}
        onSearchQueryChange={sidebar.setSearchQuery}
        onTagFilterChange={sidebar.setTagFilter}
        onToggleCollapsed={() => sidebar.setSidebarCollapsed(!sidebar.isCollapsed)}
      />

      <ScrollArea className="flex-1">
        <div className="p-2">
          <TaskRail
            isAuthenticated={sidebar.isAuthenticated}
            isCollapsed={sidebar.isCollapsed}
            runningTasks={sidebar.runningTasks}
            onOpenTaskCenter={sidebar.handleOpenTaskCenter}
            onOpenTask={sidebar.handleOpenTask}
          />
          <ConversationList
            effectiveActiveId={sidebar.effectiveActiveId}
            filteredConversations={sidebar.filteredConversations}
            groupedConversations={sidebar.groupedConversations}
            isCollapsed={sidebar.isCollapsed}
            metaByKey={sidebar.metaByKey}
            pinnedConversations={sidebar.pinnedConversations}
            onDelete={sidebar.handleDeleteConversation}
            onEditTags={sidebar.handleEditTags}
            onOpen={sidebar.openConversation}
            onResume={sidebar.handleResumeConversation}
            onTogglePin={sidebar.handleTogglePin}
            onToggleStar={sidebar.handleToggleStar}
          />
        </div>
      </ScrollArea>

      <TagEditDialog
        open={Boolean(sidebar.tagEditorItem)}
        itemTitle={sidebar.tagEditorItem?.title || ''}
        value={sidebar.tagEditorValue}
        tagOptions={sidebar.tagOptions}
        onValueChange={sidebar.setTagEditorValue}
        onOpenChange={(open) => {
          if (open) return
          sidebar.setTagEditorItem(null)
          sidebar.setTagEditorValue('')
        }}
        onSave={sidebar.handleSaveTags}
      />
    </aside>
  )
}
