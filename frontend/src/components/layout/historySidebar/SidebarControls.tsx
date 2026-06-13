import { PanelLeftClose, PanelLeftOpen, Plus, Search, Tag } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'

type SidebarControlsProps = {
  isCollapsed: boolean
  searchQuery: string
  tagFilter: string
  tagOptions: string[]
  onNewConversation: () => void
  onOpenSearch: () => void
  onSearchQueryChange: (value: string) => void
  onTagFilterChange: (value: string) => void
  onToggleCollapsed: () => void
}

export function SidebarControls({
  isCollapsed,
  searchQuery,
  tagFilter,
  tagOptions,
  onNewConversation,
  onOpenSearch,
  onSearchQueryChange,
  onTagFilterChange,
  onToggleCollapsed,
}: SidebarControlsProps) {
  const { t } = useI18n()

  return (
    <>
      <div className="aurora-history-controls flex items-center justify-between p-3">
        {!isCollapsed && (
          <Button
            onClick={onNewConversation}
            className="aurora-history-new-button flex-1 justify-start gap-2 bg-sidebar-primary text-sidebar-primary-foreground hover:bg-sidebar-primary/90 shadow-none"
            size="sm"
          >
            <Plus className="h-4 w-4" />
            {t('history.newChat')}
          </Button>
        )}
        {isCollapsed && (
          <Button
            onClick={onNewConversation}
            size="icon"
            variant="ghost"
            className="aurora-history-icon-button mx-auto h-8 w-8"
            aria-label={t('history.newChat')}
          >
            <Plus className="h-4 w-4" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className={cn('aurora-history-icon-button h-8 w-8 text-sidebar-foreground', !isCollapsed && 'ml-2')}
          onClick={onToggleCollapsed}
          aria-label={isCollapsed ? t('history.expandSidebar') : t('history.collapseSidebar')}
        >
          {isCollapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </Button>
      </div>

      {!isCollapsed && (
        <div className="aurora-history-filter-panel px-3 pb-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder={t('history.searchPlaceholder')}
              className="aurora-history-search-input h-8 border-sidebar-border bg-card pl-8 focus-visible:ring-sidebar-ring"
              value={searchQuery}
              onChange={(event) => onSearchQueryChange(event.target.value)}
            />
          </div>
          {tagOptions.length > 0 && (
            <div className="mt-2 flex items-center gap-2">
              <Tag className="h-3.5 w-3.5 text-muted-foreground" />
              <select
                className="aurora-history-tag-select h-8 flex-1 rounded-md border border-sidebar-border bg-card px-2 text-xs text-sidebar-accent-foreground"
                value={tagFilter}
                onChange={(event) => onTagFilterChange(event.target.value)}
              >
                <option value="">{t('history.allTags')}</option>
                {tagOptions.map((tag) => (
                  <option key={tag} value={tag}>
                    {tag}
                  </option>
                ))}
              </select>
            </div>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="aurora-history-search-action mt-2 w-full justify-start gap-2 text-sidebar-foreground hover:text-sidebar-accent-foreground"
            onClick={onOpenSearch}
          >
            <Search className="h-4 w-4" />
            {t('history.fullTextSearch')}
          </Button>
        </div>
      )}
    </>
  )
}
