import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { dashboardApi } from '@/api/dashboard'
import { MessageSquare, FileText, BookOpen, Brain, ArrowRight } from 'lucide-react'

const QUICK_LINKS = [
  { label: '开始对话', desc: 'AI 智能问答', path: '/chat', icon: MessageSquare },
  { label: 'AI 出题', desc: '自动生成题目', path: '/ai-generate', icon: Brain },
  { label: '试卷管理', desc: '查看所有试卷', path: '/papers', icon: FileText },
  { label: '本地题库', desc: '浏览题目库', path: '/question-library', icon: BookOpen },
]

export default function DashboardPage() {
  const { data } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => dashboardApi.get().then((r) => r.data),
  })

  const stats = data ? Object.entries(data) : []

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">概览</h1>
        <p className="text-muted-foreground text-sm mt-1">欢迎使用试卷助手</p>
      </div>

      {stats.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {stats.map(([key, val]) => (
            <div key={key} className="border rounded-xl p-4 bg-card">
              <div className="text-2xl font-bold tabular-nums">{String(val)}</div>
              <div className="text-xs text-muted-foreground mt-1">{key}</div>
            </div>
          ))}
        </div>
      )}

      <div>
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">快速入口</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {QUICK_LINKS.map(({ label, desc, path, icon: Icon }) => (
            <Link
              key={path}
              to={path}
              className="group border rounded-xl p-4 bg-card hover:bg-accent/50 transition-colors flex flex-col gap-3"
            >
              <div className="w-9 h-9 rounded-lg bg-foreground/5 flex items-center justify-center">
                <Icon size={18} className="text-foreground/70" />
              </div>
              <div>
                <div className="text-sm font-medium">{label}</div>
                <div className="text-xs text-muted-foreground mt-0.5">{desc}</div>
              </div>
              <ArrowRight size={14} className="text-muted-foreground group-hover:translate-x-0.5 transition-transform mt-auto" />
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
