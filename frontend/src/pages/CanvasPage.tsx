import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Loader2, Plus, Search, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useCanvasBoards, useCreateCanvasBoard } from '@/features/canvas/hooks'
import { formatDate } from '@/lib/utils'

export default function CanvasPage() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const boardsQuery = useCanvasBoards({ q: query || undefined, limit: 50 })
  const createBoard = useCreateCanvasBoard()

  const handleCreate = async () => {
    const board = await createBoard.mutateAsync({
      title: '未命名画布',
      snapshot: { version: 1, nodes: [] },
    })
    navigate(`/canvas/${board.id}`)
  }

  return (
    <main className="aurora-canvas-index flex h-full flex-col overflow-hidden">
      <header className="aurora-canvas-index-hero flex items-center justify-between gap-3 px-5 py-4">
        <div>
          <div className="aurora-canvas-kicker">
            <Sparkles className="h-4 w-4" />
            <span>Canvas Workspace</span>
          </div>
          <h1>学习画布</h1>
          <p>把题卡、便签、版本快照放进同一个推演工作台。</p>
        </div>
        <Button
          type="button"
          className="aurora-canvas-primary-action"
          onClick={() => void handleCreate()}
          disabled={createBoard.isPending}
        >
          {createBoard.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          新建
        </Button>
      </header>

      <section className="flex min-h-0 flex-1 flex-col p-5">
        <div className="aurora-canvas-search-strip mb-4">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索看板"
              className="pl-9"
            />
          </div>
          <span>{boardsQuery.data?.length ?? 0} 个画布</span>
        </div>

        {boardsQuery.isLoading ? (
          <div className="aurora-canvas-loading flex flex-1 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : boardsQuery.data?.length ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {boardsQuery.data.map((board) => (
              <Link key={board.id} to={`/canvas/${board.id}`} className="block">
                <Card className="aurora-canvas-board-card h-full transition hover:border-primary/50">
                  <CardHeader className="p-4">
                    <CardTitle className="truncate text-base">{board.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 p-4 pt-0 text-sm text-muted-foreground">
                    <div>{board.subject || '未设置学科'}</div>
                    <div className="aurora-canvas-board-meta">Revision {board.revision}</div>
                    <div>{formatDate(board.updatedAt || board.createdAt)}</div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        ) : (
          <div className="aurora-canvas-empty flex flex-1 items-center justify-center">
            <Button type="button" variant="outline" onClick={() => void handleCreate()} disabled={createBoard.isPending}>
              <Plus className="h-4 w-4" />
              新建第一个看板
            </Button>
          </div>
        )}
      </section>
    </main>
  )
}
