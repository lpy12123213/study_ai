import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { papersApi } from '@/api/papers'
import { FileText, Trash2 } from 'lucide-react'

export default function PapersPage() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['papers'],
    queryFn: () => papersApi.list().then((r) => r.data),
  })

  const papers: { id: string; title: string; created_at: string }[] = data?.papers ?? data ?? []

  const handleDelete = async (id: string) => {
    await papersApi.delete(id)
    refetch()
  }

  if (isLoading) return <div className="text-muted-foreground text-sm">加载中...</div>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">试卷管理</h1>
      {papers.length === 0 && <p className="text-muted-foreground text-sm">暂无试卷</p>}
      <div className="space-y-2">
        {papers.map((p) => (
          <div key={p.id} className="flex items-center gap-3 border rounded-lg px-4 py-3 bg-card hover:bg-accent/30 transition-colors">
            <FileText size={16} className="text-muted-foreground shrink-0" />
            <Link to={`/papers/${p.id}`} className="flex-1 text-sm font-medium hover:underline truncate">
              {p.title || '未命名试卷'}
            </Link>
            <span className="text-xs text-muted-foreground">{new Date(p.created_at).toLocaleDateString('zh-CN')}</span>
            <button onClick={() => handleDelete(p.id)} className="p-1 hover:text-destructive transition-colors">
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
