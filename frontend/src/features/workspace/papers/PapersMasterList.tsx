import { useEffect, useMemo, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { ClipboardCheck, Loader2, MoreHorizontal, Pin, Search, Star, Tag, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { TagEditDialog, useTagEditor } from '@/components/shared/TagEditDialog'
import { usePapers, useDeletePaper } from '@/hooks/usePapers'
import { useStartExam } from '@/hooks/useExam'
import { useNotificationStore } from '@/stores/useNotificationStore'
import { cn, formatDate } from '@/lib/utils'
import { usePaperMeta } from './usePaperMeta'

export default function PapersMasterList() {
  const [search, setSearch] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const navigate = useNavigate()
  const addToast = useNotificationStore((s) => s.addToast)

  const { data: papers, isLoading } = usePapers({ limit: 200 })
  const { mutate: deletePaper, isPending: isDeleting } = useDeletePaper()
  const startExam = useStartExam()
  const { byId: metaById, tagOptions, updateMeta } = usePaperMeta()

  useEffect(() => {
    if (tagFilter && !tagOptions.includes(tagFilter)) setTagFilter('')
  }, [tagFilter, tagOptions])

  type PaperRow = NonNullable<typeof papers>[number]
  const tagEditor = useTagEditor<PaperRow>({
    getItemId: (paper) => String(paper.id),
    getInitialValue: (paper) => (metaById.get(String(paper.id))?.tags || []).join(', '),
    onSave: (paper, tags) => {
      updateMeta.mutate({ itemId: String(paper.id), patch: { tags } })
    },
  })

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = (papers || []).filter((p) => {
      const meta = metaById.get(String(p.id))
      if (tagFilter && !(meta?.tags || []).includes(tagFilter)) return false
      if (!q) return true
      const inTitle = p.name.toLowerCase().includes(q)
      const inTags = (meta?.tags || []).some((t) => String(t || '').toLowerCase().includes(q))
      return inTitle || inTags
    })
    list.sort((a, b) => {
      const ma = metaById.get(String(a.id))
      const mb = metaById.get(String(b.id))
      const pa = ma?.pinned ? 1 : 0
      const pb = mb?.pinned ? 1 : 0
      if (pa !== pb) return pb - pa
      return String(b.createdAt || '').localeCompare(String(a.createdAt || ''))
    })
    return list
  }, [papers, metaById, search, tagFilter])

  const handleDelete = () => {
    if (deleteId) {
      deletePaper(deleteId)
      setDeleteId(null)
    }
  }

  const startUntimedExam = async (paperId: number) => {
    try {
      const session = await startExam.mutateAsync({ paperId, mode: 'untimed' })
      navigate(`/exam/${session.sessionId}`)
    } catch {
      addToast({ title: '开始答题失败', status: 'failed' })
    }
  }

  return (
    <>
      <div className="space-y-2 px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索试卷..."
            className="h-8 bg-background/45 pl-8 text-sm"
          />
        </div>
        {tagOptions.length > 0 && (
          <select
            className="h-8 w-full rounded-md border border-input bg-background/45 px-2 text-xs"
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
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-2">
        {isLoading && <div className="px-2 py-3 text-xs text-muted-foreground">加载中...</div>}
        {!isLoading && filtered.length === 0 && (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            {search || tagFilter ? '没有匹配的试卷' : '暂无试卷'}
          </div>
        )}
        {filtered.map((paper) => {
          const meta = metaById.get(String(paper.id))
          const tags = meta?.tags || []
          return (
            <div key={paper.id} className="group relative">
              <NavLink
                to={`/papers/${encodeURIComponent(String(paper.id))}`}
                className={({ isActive }) =>
                  cn(
                    'aurora-split-nav-item mb-1 block rounded-md px-3 py-2 text-sm transition-colors',
                    isActive
                      ? 'aurora-split-nav-item-active bg-accent text-accent-foreground'
                      : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                  )
                }
              >
                <div className="flex min-w-0 items-center gap-1.5 pr-6">
                  {meta?.pinned && <Pin className="h-3 w-3 shrink-0 text-primary" />}
                  {meta?.starred && <Star className="h-3 w-3 shrink-0 text-primary" />}
                  <span className="truncate font-medium">{paper.name}</span>
                </div>
                <div className="mt-0.5 truncate text-xs opacity-70">
                  {paper.questionCount} 题{paper.createdAt ? ` · ${formatDate(paper.createdAt)}` : ''}
                  {tags.length > 0 ? ` · ${tags.slice(0, 2).join(' / ')}` : ''}
                </div>
              </NavLink>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="absolute right-1.5 top-1.5 h-7 w-7 text-muted-foreground opacity-60 hover:opacity-100 lg:opacity-0 lg:group-hover:opacity-100 lg:focus-visible:opacity-100"
                    aria-label="试卷操作"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => startUntimedExam(Number(paper.id))}>
                    <ClipboardCheck className="h-4 w-4" />
                    开始答题
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => updateMeta.mutate({ itemId: String(paper.id), patch: { starred: !meta?.starred } })}
                  >
                    <Star className="h-4 w-4" />
                    {meta?.starred ? '取消收藏' : '收藏'}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => updateMeta.mutate({ itemId: String(paper.id), patch: { pinned: !meta?.pinned } })}
                  >
                    <Pin className="h-4 w-4" />
                    {meta?.pinned ? '取消置顶' : '置顶'}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => tagEditor.open(paper)}>
                    <Tag className="h-4 w-4" />
                    设置标签
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onSelect={() => setDeleteId(String(paper.id))}
                  >
                    <Trash2 className="h-4 w-4" />
                    删除
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )
        })}
      </div>

      <Dialog open={!!deleteId} onOpenChange={(open) => !open && setDeleteId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除试卷？</DialogTitle>
            <DialogDescription>此操作无法撤销。试卷将被永久删除。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteId(null)}>取消</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={isDeleting}>
              {isDeleting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <TagEditDialog
        open={tagEditor.isOpen}
        itemTitle={tagEditor.editing?.name || ''}
        value={tagEditor.value}
        tagOptions={tagOptions}
        onValueChange={tagEditor.setValue}
        onOpenChange={(open) => {
          if (!open) tagEditor.close()
        }}
        onSave={tagEditor.save}
      />
    </>
  )
}
