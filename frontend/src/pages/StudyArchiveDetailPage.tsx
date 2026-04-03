import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BookOpen, Loader2, Search, Share2, Download, ListTodo, MessageSquarePlus, Star, Pin, Tag } from 'lucide-react'
import { getStudyArchive } from '@/api/studyArchives'
import { SecureMarkdown } from '@/components/shared/SecureMarkdown'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { ShareLinkDialog } from '@/components/shared/ShareLinkDialog'
import { AnnotationDialog } from '@/components/shared/AnnotationDialog'
import { useNotificationStore } from '@/stores/useNotificationStore'
import * as tasksApi from '@/api/tasks'
import * as learningPlansApi from '@/api/learningPlans'
import * as metaApi from '@/api/meta'

type Block = {
  id: string
  title?: string
  markdown: string
}

function toText(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

export default function StudyArchiveDetailPage() {
  const { archiveId } = useParams<{ archiveId: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const q = (searchParams.get('q') || '').trim()
  const pushToast = useNotificationStore((s) => s.pushToast)
  const queryClient = useQueryClient()
  const [shareOpen, setShareOpen] = useState(false)
  const [annotateOpen, setAnnotateOpen] = useState(false)
  const [annotateAnchor, setAnnotateAnchor] = useState<string>('')
  const [annotateSnippet, setAnnotateSnippet] = useState<string>('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['studyArchive', archiveId],
    queryFn: () => getStudyArchive(String(archiveId || '')),
    enabled: Boolean(archiveId),
  })

  const { data: meta } = useQuery({
    queryKey: ['itemMeta', 'study_archive', archiveId],
    queryFn: () => metaApi.getMeta('study_archive', String(archiveId || '')),
    enabled: Boolean(archiveId),
    staleTime: 30_000,
  })

  const updateMeta = useMutation({
    mutationFn: (patch: { starred?: boolean; pinned?: boolean; tags?: string[] }) =>
      metaApi.setMeta('study_archive', String(archiveId || ''), patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['itemMeta', 'study_archive', archiveId] }),
  })

  const blocks = useMemo<Block[]>(() => {
    const md = toText((data as any)?.markdown)
    const sections = (data as any)?.sections
    if (Array.isArray(sections) && sections.length > 0) {
      const out: Block[] = []
      sections.forEach((s: any, idx: number) => {
        const title = toText(s?.title || s?.name || '')
        const content = toText(s?.content || s?.markdown || '')
        if (!title && !content) return
        out.push({ id: `section-${idx}`, title: title || undefined, markdown: content })
      })
      if (out.length > 0) return out
    }
    return [{ id: 'full', title: undefined, markdown: md }]
  }, [data])

  const hitBlockId = useMemo(() => {
    if (!q) return null
    const needle = q.toLowerCase()
    for (const b of blocks) {
      const hay = `${b.title || ''}\n${b.markdown || ''}`.toLowerCase()
      if (hay.includes(needle)) return b.id
    }
    return null
  }, [blocks, q])

  useEffect(() => {
    if (!hitBlockId) return
    const el = document.getElementById(hitBlockId)
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [hitBlockId])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <div className="h-16 w-16 bg-muted rounded-full flex items-center justify-center mb-4">
          <BookOpen className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-medium mb-2">资料不存在</h3>
        <p className="text-muted-foreground mb-6">加载失败或已被删除</p>
        <Button asChild variant="outline">
          <Link to="/study-materials">返回自学资料</Link>
        </Button>
      </div>
    )
  }

  const title = `${toText((data as any)?.subject)} ${toText((data as any)?.topic)}`.trim() || `自学资料 #${String(archiveId)}`
  const isStarred = Boolean((meta as any)?.starred)
  const isPinned = Boolean((meta as any)?.pinned)

  const exportMarkdown = async () => {
    if (!archiveId) return
    try {
      const { taskId } = await tasksApi.exportStudyArchiveTask(archiveId, { format: 'markdown' })
      if (taskId) {
        pushToast({ id: `export-${taskId}`, title: '已加入导出队列', taskId, status: 'running' })
        navigate('/exports')
      }
    } catch {
      pushToast({ id: `export-archive-failed-${archiveId}`, title: '导出失败' })
    }
  }

  const createPlan = async () => {
    if (!archiveId) return
    try {
      const plan = await learningPlansApi.createLearningPlanFromStudyArchive(Number(archiveId), {})
      navigate(`/learning-plans?planId=${plan.id}`)
    } catch {
      pushToast({ id: `learning-plan-failed-${archiveId}`, title: '创建学习计划失败' })
    }
  }

  return (
    <div className="h-full flex flex-col bg-background">
      <div className="border-b border-border p-4 flex items-center justify-between sticky top-0 bg-background/80 backdrop-blur-sm z-10">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild className="rounded-full">
            <Link to="/study-materials" aria-label="返回">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div className="min-w-0">
            <div className="font-semibold text-sm truncate">{title}</div>
            {!!q && (
              <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                <Search className="h-3.5 w-3.5" />
                已定位关键词：<span className="font-mono">{q}</span>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => updateMeta.mutate({ starred: !isStarred })}
            aria-label="收藏"
            title="收藏"
          >
            <Star className={cn('h-4 w-4', isStarred && 'text-primary')} />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => updateMeta.mutate({ pinned: !isPinned })}
            aria-label="置顶"
            title="置顶"
          >
            <Pin className={cn('h-4 w-4', isPinned && 'text-primary')} />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => {
              const current = Array.isArray((meta as any)?.tags) ? (((meta as any).tags as string[]) || []).join(', ') : ''
              const raw = window.prompt('标签（逗号分隔）', current)
              if (raw == null) return
              const tags = raw
                .split(',')
                .map((t) => t.trim())
                .filter((t) => t.length > 0)
                .slice(0, 20)
              updateMeta.mutate({ tags })
            }}
            aria-label="设置标签"
            title="设置标签"
          >
            <Tag className="h-4 w-4" />
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={createPlan}>
            <ListTodo className="h-4 w-4 mr-2" />
            学习计划
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={exportMarkdown}>
            <Download className="h-4 w-4 mr-2" />
            导出
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => setShareOpen(true)}>
            <Share2 className="h-4 w-4 mr-2" />
            分享
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="max-w-4xl mx-auto p-6 space-y-4">
          {blocks.map((b) => {
            const isHit = hitBlockId === b.id
            return (
              <div
                key={b.id}
                id={b.id}
                className={cn(
                  'rounded-xl border border-border/60 bg-card p-5',
                  isHit && 'border-primary/40 ring-2 ring-primary/10',
                )}
              >
                <div className="flex items-start justify-between gap-3 mb-3">
                  {b.title ? <div className="font-medium">{b.title}</div> : <div />}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8"
                    onClick={() => {
                      setAnnotateAnchor(b.id)
                      setAnnotateSnippet(String(b.title || '').trim())
                      setAnnotateOpen(true)
                    }}
                    aria-label="添加批注"
                  >
                    <MessageSquarePlus className="h-4 w-4 mr-2" />
                    批注
                  </Button>
                </div>
                <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-7">
                  <SecureMarkdown markdown={b.markdown} />
                </div>
              </div>
            )
          })}
        </div>
      </ScrollArea>

      <ShareLinkDialog
        open={shareOpen}
        onOpenChange={setShareOpen}
        itemType="study_archive"
        itemId={String(archiveId || '')}
        title={title}
      />

      <AnnotationDialog
        open={annotateOpen}
        onOpenChange={setAnnotateOpen}
        itemType="study_archive"
        itemId={String(archiveId || '')}
        anchor={annotateAnchor}
        snippet={annotateSnippet}
      />
    </div>
  )
}
