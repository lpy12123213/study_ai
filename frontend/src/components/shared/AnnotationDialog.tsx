import { useMemo, useState } from 'react'
import { Loader2, Tag } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import * as annotationsApi from '@/api/annotations'

function parseTags(value: string): string[] {
  return String(value || '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 12)
}

export function AnnotationDialog(props: {
  open: boolean
  onOpenChange: (open: boolean) => void
  itemType: string
  itemId: string
  anchor?: string
  snippet?: string
}) {
  const { open, onOpenChange, itemType, itemId, anchor, snippet } = props
  const [content, setContent] = useState('')
  const [tagsText, setTagsText] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const tags = useMemo(() => parseTags(tagsText), [tagsText])

  const save = async () => {
    setIsSaving(true)
    setError(null)
    try {
      await annotationsApi.createAnnotation({
        item_type: itemType,
        item_id: itemId,
        anchor,
        snippet,
        content,
        tags,
      })
      setContent('')
      setTagsText('')
      onOpenChange(false)
    } catch (e) {
      setError(e)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>添加批注</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          {snippet && (
            <div className="text-xs text-muted-foreground rounded-md border bg-muted/20 p-2 whitespace-pre-wrap">
              {snippet}
            </div>
          )}

          {Boolean(error) && <ErrorNotice error={error} />}

          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="写下你的批注/疑问/总结…"
            className="min-h-28"
          />

          <div className="space-y-1.5">
            <div className="text-sm font-medium flex items-center gap-2">
              <Tag className="h-4 w-4" />
              标签（逗号分隔，可选）
            </div>
            <Input value={tagsText} onChange={(e) => setTagsText(e.target.value)} placeholder="例如：未解决, 重点, 易错" />
          </div>

          <div className="flex items-center justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button type="button" onClick={save} disabled={isSaving || !content.trim()}>
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : '保存'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
