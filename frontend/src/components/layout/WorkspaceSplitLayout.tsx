import { lazy, Suspense, useMemo, useState } from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import { FileText, Layers, Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { useMasterList, type MasterListKind } from '@/features/workspace/useMasterList'
import { cn } from '@/lib/utils'

const PapersMasterList = lazy(() => import('@/features/workspace/papers/PapersMasterList'))

type SplitKind = 'papers' | 'lesson-plans' | 'study-archives'

const splitMeta: Record<SplitKind, { title: string; empty: string; icon: typeof FileText }> = {
  papers: { title: '试卷', empty: '暂无试卷', icon: FileText },
  'lesson-plans': { title: '教案', empty: '暂无教案', icon: Layers },
  'study-archives': { title: '学习档案', empty: '暂无学习档案', icon: FileText },
}

function GenericMasterList({ kind }: { kind: MasterListKind }) {
  const [search, setSearch] = useState('')
  const { data: items = [], isLoading } = useMasterList(kind)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter(
      (item) => item.title.toLowerCase().includes(q) || (item.subtitle || '').toLowerCase().includes(q),
    )
  }, [items, search])

  return (
    <>
      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索..."
            className="h-8 bg-background/45 pl-8 text-sm"
          />
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-2">
        {isLoading && <div className="px-2 py-3 text-xs text-muted-foreground">加载中...</div>}
        {!isLoading && filtered.length === 0 && (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            {search ? '没有匹配的结果' : splitMeta[kind].empty}
          </div>
        )}
        {filtered.map((item) => (
          <NavLink
            key={item.id}
            to={item.to}
            className={({ isActive }) =>
              cn(
                'aurora-split-nav-item mb-1 block rounded-md px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'aurora-split-nav-item-active bg-accent text-accent-foreground'
                  : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
              )
            }
          >
            <div className="truncate font-medium">{item.title}</div>
            {item.subtitle && <div className="mt-0.5 truncate text-xs opacity-70">{item.subtitle}</div>}
          </NavLink>
        ))}
      </div>
    </>
  )
}

export function WorkspaceSplitLayout({ kind }: { kind: SplitKind }) {
  const meta = splitMeta[kind]
  const Icon = meta.icon
  const params = useParams()
  const inDetail = Object.keys(params).length > 0

  return (
    <div className="aurora-split-workspace flex h-full min-h-0 overflow-hidden">
      <aside
        className={cn(
          'aurora-split-sidebar shrink-0 lg:flex lg:w-72 lg:flex-col',
          inDetail ? 'hidden' : 'flex w-full flex-col',
        )}
      >
        <div className="aurora-split-sidebar-head px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Icon className="h-4 w-4 text-muted-foreground" />
            {meta.title}
          </div>
        </div>
        {kind === 'papers' ? (
          <Suspense fallback={<div className="px-4 py-3 text-xs text-muted-foreground">加载中...</div>}>
            <PapersMasterList />
          </Suspense>
        ) : (
          <GenericMasterList kind={kind} />
        )}
      </aside>
      <main
        className={cn(
          'aurora-split-main min-w-0 flex-1 overflow-auto lg:block',
          inDetail ? 'block' : 'hidden',
        )}
      >
        <Outlet />
      </main>
    </div>
  )
}
