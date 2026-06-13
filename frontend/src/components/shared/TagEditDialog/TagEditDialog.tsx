import { useMemo } from 'react'
import { Check, Tag, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useI18n } from '@/i18n'
import { parseTagsInput } from './utils'

type TagEditDialogProps = {
  open: boolean
  itemTitle: string
  value: string
  tagOptions?: string[]
  onValueChange: (value: string) => void
  onOpenChange: (open: boolean) => void
  onSave: () => void
}

/**
 * Tag editor dialog used by master-detail pages (Papers, StudyArchives, ...).
 *
 * Replaces ad-hoc `window.prompt('标签')` calls so users get a multi-tag combobox
 * with existing-tag suggestions, on-mobile keyboard handling and i18n labels.
 */
export function TagEditDialog({
  open,
  itemTitle,
  value,
  tagOptions = [],
  onValueChange,
  onOpenChange,
  onSave,
}: TagEditDialogProps) {
  const { t } = useI18n()
  const selectedTags = useMemo(() => parseTagsInput(value), [value])
  const selectedTagSet = useMemo(() => new Set(selectedTags), [selectedTags])
  const candidateTags = useMemo(
    () => tagOptions.filter((tag) => !selectedTagSet.has(tag)),
    [tagOptions, selectedTagSet],
  )

  const setTags = (tags: string[]) => {
    onValueChange(
      Array.from(new Set(tags.map((tag) => tag.trim()).filter(Boolean))).slice(-20).join(', '),
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="aurora-tag-dialog sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{t('tagDialog.title')}</DialogTitle>
          <DialogDescription className="truncate">{itemTitle}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="shared-tag-editor">
              {t('tagDialog.label')}
            </label>
            <Input
              id="shared-tag-editor"
              value={value}
              onChange={(event) => onValueChange(event.target.value)}
              placeholder={t('tagDialog.placeholder')}
              className="aurora-tag-dialog-input"
            />
          </div>

          {selectedTags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {selectedTags.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  className="aurora-tag-dialog-pill inline-flex items-center gap-1 rounded-md border border-border bg-secondary px-2 py-1 text-xs text-secondary-foreground"
                  onClick={() => setTags(selectedTags.filter((item) => item !== tag))}
                >
                  {tag}
                  <X className="h-3 w-3" />
                </button>
              ))}
            </div>
          )}

          {candidateTags.length > 0 && (
            <Command className="aurora-tag-dialog-command rounded-md border border-border">
              <CommandInput className="aurora-tag-dialog-input" placeholder={t('tagDialog.searchPlaceholder')} />
              <CommandList>
                <CommandEmpty>{t('tagDialog.empty')}</CommandEmpty>
                <CommandGroup heading={t('tagDialog.existing')}>
                  {candidateTags.map((tag) => (
                    <CommandItem
                      key={tag}
                      className="aurora-tag-dialog-command-item"
                      value={tag}
                      onSelect={() => setTags([...selectedTags, tag])}
                    >
                      <Tag className="mr-2 h-3.5 w-3.5" />
                      <span>{tag}</span>
                      <Check className="ml-auto h-3.5 w-3.5 opacity-0" />
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          )}
        </div>

        <DialogFooter>
          <Button type="button" className="aurora-tag-dialog-secondary" variant="outline" onClick={() => onOpenChange(false)}>
            {t('tagDialog.cancel')}
          </Button>
          <Button type="button" className="aurora-tag-dialog-primary" onClick={onSave}>
            {t('tagDialog.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
