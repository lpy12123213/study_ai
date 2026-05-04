import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FileText, Layers, Sparkles } from 'lucide-react'
import { getPapers } from '@/api/papers'
import { getLessonPlans } from '@/api/lessonPlans'
import { listStudyArchives } from '@/api/studyArchives'
import { cn, formatDate } from '@/lib/utils'

type SplitKind = 'papers' | 'lesson-plans' | 'study-archives' | 'ai-generate'

type SplitItem = {
  id: string
  title: string
  subtitle?: string
  to: string
}

const splitMeta: Record<SplitKind, { title: string; empty: string; icon: typeof FileText }> = {
  papers: { title: '试卷', empty: '暂无试卷', icon: FileText },
  'lesson-plans': { title: '教案', empty: '暂无教案', icon: Layers },
  'study-archives': { title: '学习档案', empty: '暂无学习档案', icon: FileText },
  'ai-generate': { title: 'AI 出题', empty: '暂无审核上下文', icon: Sparkles },
}

async function loadSplitItems(kind: SplitKind): Promise<SplitItem[]> {
  if (kind === 'papers') {
    const papers = await getPapers({ limit: 100 })
    return papers.map((paper) => ({
      id: String(paper.id || ''),
      title: paper.name || '未命名试卷',
      subtitle: paper.createdAt ? formatDate(paper.createdAt) : undefined,
      to: `/papers/${encodeURIComponent(String(paper.id || ''))}`,
    })).filter((item: SplitItem) => item.id)
  }

  if (kind === 'lesson-plans') {
    const plans = await getLessonPlans()
    return plans.map((plan) => ({
      id: String(plan.id || ''),
      title: String(plan.title || '未命名教案'),
      subtitle: [plan.subject, plan.grade].filter(Boolean).join(' · ') || undefined,
      to: `/lesson-plans/${encodeURIComponent(String(plan.id || ''))}`,
    })).filter((item) => item.id)
  }

  if (kind === 'study-archives') {
    const archives = await listStudyArchives({ limit: 80 })
    return archives.map((archive) => ({
      id: String(archive.id || ''),
      title: [archive.subject, archive.topic].filter(Boolean).join(' · ') || `学习档案 #${archive.id}`,
      subtitle: archive.updated_at || archive.created_at ? formatDate(String(archive.updated_at || archive.created_at)) : undefined,
      to: `/study-archives/${encodeURIComponent(String(archive.id || ''))}`,
    })).filter((item) => item.id)
  }

  return [{ id: 'studio', title: '生成工作台', subtitle: '草稿、审核与入库', to: '/ai-generate' }]
}

export function WorkspaceSplitLayout({ kind }: { kind: SplitKind }) {
  const meta = splitMeta[kind]
  const Icon = meta.icon
  const { data: items = [], isLoading } = useQuery({
    queryKey: ['workspaceSplit', kind],
    queryFn: () => loadSplitItems(kind),
    staleTime: 30_000,
  })

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      <aside className="hidden w-72 shrink-0 border-r border-border bg-background/60 lg:flex lg:flex-col">
        <div className="border-b border-border px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Icon className="h-4 w-4 text-muted-foreground" />
            {meta.title}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-2">
          {isLoading && <div className="px-2 py-3 text-xs text-muted-foreground">加载中...</div>}
          {!isLoading && items.length === 0 && <div className="px-2 py-3 text-xs text-muted-foreground">{meta.empty}</div>}
          {items.map((item) => (
            <NavLink
              key={item.id}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  'mb-1 block rounded-md px-3 py-2 text-sm transition-colors',
                  isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
                )
              }
            >
              <div className="truncate font-medium">{item.title}</div>
              {item.subtitle && <div className="mt-0.5 truncate text-xs opacity-70">{item.subtitle}</div>}
            </NavLink>
          ))}
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
