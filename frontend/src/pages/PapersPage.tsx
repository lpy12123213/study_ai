import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, Search, Trash2, Loader2, Plus, Calendar } from 'lucide-react'
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
import { usePapers, useDeletePaper } from '@/hooks/usePapers'
import { formatDate } from '@/lib/utils'

export default function PapersPage() {
  const [search, setSearch] = useState('')
  const [deleteId, setDeleteId] = useState<string | null>(null)

  const { data: papers, isLoading } = usePapers({ limit: 200 })
  const { mutate: deletePaper, isPending: isDeleting } = useDeletePaper()

  const handleDelete = () => {
    if (deleteId) {
      deletePaper(deleteId)
      setDeleteId(null)
    }
  }

  const filtered =
    papers?.filter((p) => {
      if (!search.trim()) return true
      return p.name.toLowerCase().includes(search.trim().toLowerCase())
    }) ?? []

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
                    <Link
                      to={`/papers/${paper.id}`}
                      className="block font-medium truncate hover:text-primary transition-colors"
                    >
                      {paper.name}
                    </Link>
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
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={() => setDeleteId(String(paper.id))}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
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
    </div>
  )
}
