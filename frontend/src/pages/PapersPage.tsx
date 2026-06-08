import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ClipboardCheck, FileText, Search, Trash2, Loader2, Plus, Calendar, Star, Pin, Tag } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { TagEditDialog, useTagEditor } from '@/components/shared/TagEditDialog'
import { usePapers, useDeletePaper } from '@/hooks/usePapers'
import { useStartExam } from '@/hooks/useExam'
import { cn, formatDate } from '@/lib/utils'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as metaApi from '@/api/meta'
import { useNotificationStore } from '@/stores/useNotificationStore'

export default function PapersPage() {
  const [search, setSearch] = useState('')
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [tagFilter, setTagFilter] = useState('')
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const addToast = useNotificationStore((s) => s.addToast)

  const { data: papers, isLoading } = usePapers({ limit: 200 })
  const { mutate: deletePaper, isPending: isDeleting } = useDeletePaper()
  const startExam = useStartExam()

  const { data: paperMetaResp } = useQuery({
    queryKey: ['itemMeta', 'paper'],
    queryFn: () => metaApi.listMeta({ itemType: 'paper', limit: 500 }),
  })

  const paperMetaItems: metaApi.ItemMeta[] = useMemo(() => paperMetaResp?.items ?? [], [paperMetaResp])
  const paperMetaById = useMemo(() => {
    const m = new Map<string, metaApi.ItemMeta>()
    for (const row of paperMetaItems) {
      m.set(String(row.item_id), row)
    }
    return m
  }, [paperMetaItems])

  const tagOptions = useMemo(() => {
    const set = new Set<string>()
    for (const row of paperMetaItems) {
      const tags = Array.isArray(row.tags) ? row.tags : []
      for (const t of tags) {
        const v = String(t || '').trim()
        if (v) set.add(v)
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  }, [paperMetaItems])

  useEffect(() => {
    if (tagFilter && !tagOptions.includes(tagFilter)) setTagFilter('')
  }, [tagFilter, tagOptions])

  const updateMeta = useMutation({
    mutationFn: (args: { itemId: string; patch: { starred?: boolean; pinned?: boolean; tags?: string[] } }) =>
      metaApi.setMeta('paper', args.itemId, args.patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['itemMeta', 'paper'] })
    },
  })

  type PaperRow = NonNullable<typeof papers>[number]
  const tagEditor = useTagEditor<PaperRow>({
    getItemId: (paper) => String(paper.id),
    getInitialValue: (paper) => (paperMetaById.get(String(paper.id))?.tags || []).join(', '),
    onSave: (paper, tags) => {
      updateMeta.mutate({ itemId: String(paper.id), patch: { tags } })
    },
  })

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

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = (papers || []).filter((p) => {
      const meta = paperMetaById.get(String(p.id))
      if (tagFilter && !(meta?.tags || []).includes(tagFilter)) return false
      if (!q) return true
      const inTitle = p.name.toLowerCase().includes(q)
      const inTags = (meta?.tags || []).some((t) => String(t || '').toLowerCase().includes(q))
      return inTitle || inTags
    })
    list.sort((a, b) => {
      const ma = paperMetaById.get(String(a.id))
      const mb = paperMetaById.get(String(b.id))
      const pa = ma?.pinned ? 1 : 0
      const pb = mb?.pinned ? 1 : 0
      if (pa !== pb) return pb - pa
      return String(b.createdAt || '').localeCompare(String(a.createdAt || ''))
    })
    return list
  }, [papers, paperMetaById, search, tagFilter])

  return (
    <div className="h-full p-6 overflow-auto">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold tracking-tight mb-1">试卷管理</h1>
            <p className="text-muted-foreground text-sm">
              管理和导出已生成的试卷
            </p>
          </div>
          <Button asChild className="gap-2 shadow-sm">
            <Link to="/blueprint">
              <Plus className="h-4 w-4" />
              新建试卷
            </Link>
          </Button>
        </div>

        <div className="relative mb-6">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索试卷..."
            className="pl-9 max-w-sm bg-background"
          />
        </div>

        {tagOptions.length > 0 && (
          <div className="mb-6 max-w-sm flex items-center gap-2">
            <Tag className="h-4 w-4 text-muted-foreground" />
            <select
              className="h-9 rounded-md border border-input bg-background px-2 text-sm flex-1"
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

        {isLoading ? (
          <div className="rounded-xl border border-border bg-card overflow-hidden shadow-sm">
            <div className="grid grid-cols-12 gap-4 px-6 py-3 border-b border-border bg-muted/30">
              <div className="col-span-6"><Skeleton className="h-4 w-24" /></div>
              <div className="col-span-2 flex justify-center"><Skeleton className="h-4 w-12" /></div>
              <div className="col-span-3"><Skeleton className="h-4 w-20" /></div>
              <div className="col-span-1 flex justify-end"><Skeleton className="h-4 w-8" /></div>
            </div>
            <div className="divide-y divide-border/50">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="grid grid-cols-12 gap-4 px-6 py-4 items-center">
                  <div className="col-span-6">
                    <Skeleton className="h-5 w-48 mb-2" />
                    <Skeleton className="h-3 w-32" />
                  </div>
                  <div className="col-span-2 flex justify-center">
                    <Skeleton className="h-5 w-12 rounded-full" />
                  </div>
                  <div className="col-span-3">
                    <Skeleton className="h-4 w-24" />
                  </div>
                  <div className="col-span-1 flex justify-end">
                    <Skeleton className="h-8 w-8 rounded-md" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : filtered.length > 0 ? (
          <div className="rounded-xl border border-border bg-card overflow-hidden shadow-sm">
            <div className="grid grid-cols-12 gap-4 px-6 py-3 border-b border-border bg-muted/30 text-xs font-medium text-muted-foreground">
              <div className="col-span-6">试卷名称</div>
              <div className="col-span-2 text-center">题目数量</div>
              <div className="col-span-3">创建时间</div>
              <div className="col-span-1 text-right">操作</div>
            </div>
            
            <div className="divide-y divide-border/50">
              {filtered.map((paper) => (
                <div
                  key={paper.id}
                  className="grid grid-cols-12 gap-4 px-6 py-4 items-center hover:bg-muted/30 transition-colors group"
                >
                  <div className="col-span-6 min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-foreground"
                        onClick={() => {
                          const meta = paperMetaById.get(String(paper.id))
                          updateMeta.mutate({ itemId: String(paper.id), patch: { starred: !meta?.starred } })
                        }}
                        aria-label="收藏"
                        title="收藏"
                      >
                        <Star className={cn('h-4 w-4', paperMetaById.get(String(paper.id))?.starred ? 'text-primary' : '')} />
                      </button>
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-foreground"
                        onClick={() => {
                          const meta = paperMetaById.get(String(paper.id))
                          updateMeta.mutate({ itemId: String(paper.id), patch: { pinned: !meta?.pinned } })
                        }}
                        aria-label="置顶"
                        title="置顶"
                      >
                        <Pin className={cn('h-4 w-4', paperMetaById.get(String(paper.id))?.pinned ? 'text-primary' : '')} />
                      </button>
                      <Link
                        to={`/papers/${paper.id}`}
                        className="block font-medium truncate hover:text-primary transition-colors min-w-0"
                      >
                        {paper.name}
                      </Link>
                      {(paperMetaById.get(String(paper.id))?.tags || []).slice(0, 2).map((t) => (
                        <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground shrink-0">
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="col-span-2 text-center">
                    <Badge variant="secondary" className="font-normal text-xs">
                      {paper.questionCount} 题
                    </Badge>
                  </div>
                  <div className="col-span-3 text-sm text-muted-foreground flex items-center gap-2">
                    <Calendar className="h-3.5 w-3.5" />
                    {paper.createdAt ? formatDate(paper.createdAt) : '-'}
                  </div>
                  <div className="col-span-1 text-right">
                    <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground"
                        onClick={() => startUntimedExam(Number(paper.id))}
                        aria-label="答题"
                        title="答题"
                      >
                        <ClipboardCheck className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground"
                        onClick={() => tagEditor.open(paper)}
                        aria-label="设置标签"
                        title="设置标签"
                      >
                        <Tag className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-muted-foreground hover:text-destructive"
                        onClick={() => setDeleteId(String(paper.id))}
                        aria-label="删除"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="h-20 w-20 bg-muted/50 rounded-full flex items-center justify-center mb-4">
              <FileText className="h-10 w-10 text-muted-foreground/50" />
            </div>
            <h3 className="text-lg font-medium mb-1">暂无试卷</h3>
            <p className="text-muted-foreground text-sm mb-6 max-w-xs">
              还没有生成任何试卷。点击右上角“新建试卷”开始组卷。
            </p>
            <Button asChild variant="outline">
              <Link to="/blueprint">去组卷</Link>
            </Button>
          </div>
        )}
      </div>

      <Dialog open={!!deleteId} onOpenChange={(open) => !open && setDeleteId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除试卷？</DialogTitle>
            <DialogDescription>
              此操作无法撤销。试卷将被永久删除。
            </DialogDescription>
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
    </div>
  )
}
