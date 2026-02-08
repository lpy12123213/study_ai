import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { FileText, Search, Trash2, Loader2, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { usePapers, useDeletePaper } from '@/hooks/usePapers'
import { formatDate } from '@/lib/utils'

export default function PapersPage() {
  const [search, setSearch] = useState('')

  const { data: papers, isLoading } = usePapers({ limit: 200 })
  const { mutate: deletePaper } = useDeletePaper()

  const handleDelete = (id: number) => {
    if (confirm('确定要删除这份试卷吗？')) {
      deletePaper(String(id))
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
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold mb-2">试卷管理</h1>
            <p className="text-muted-foreground">
              管理和导出已生成的试卷
            </p>
          </div>
          <Button asChild>
            <Link to="/blueprint">
              <Plus className="h-4 w-4 mr-2" />
              新建试卷
            </Link>
          </Button>
        </div>

        <div className="flex items-center gap-4 mb-6">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索试卷..."
              className="pl-10"
            />
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : filtered.length > 0 ? (
          <>
            <div className="grid gap-4">
              {filtered.map((paper, index) => (
                <motion.div
                  key={paper.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                >
                  <Card className="hover:shadow-md transition-shadow">
                    <CardContent className="p-4">
                      <div className="flex items-start justify-between">
                        <Link
                          to={`/papers/${paper.id}`}
                          className="flex-1 hover:opacity-80"
                        >
                          <h3 className="font-semibold mb-1">{paper.name}</h3>
                          <div className="flex items-center gap-3 text-sm text-muted-foreground">
                            <Badge variant="secondary">试卷</Badge>
                            <span>{paper.questionCount} 道题</span>
                            {!!paper.createdAt && (
                              <span>{formatDate(paper.createdAt)}</span>
                            )}
                          </div>
                        </Link>

                        <div className="flex items-center gap-2">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="text-muted-foreground hover:text-destructive"
                            onClick={() => handleDelete(paper.id)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              ))}
            </div>
          </>
        ) : (
          <div className="text-center py-12 text-muted-foreground">
            <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p>暂无试卷</p>
            <Button asChild className="mt-4">
              <Link to="/blueprint">去组卷</Link>
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
