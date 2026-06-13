import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BookOpen, Loader2, Search, Share2, Download, ListTodo, MessageSquarePlus, Star, Pin, Tag, Film, Sparkles } from 'lucide-react'
import { getStudyArchive } from '@/api/studyArchives'
import { Markdown } from '@/components/shared/Markdown'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { ShareLinkDialog } from '@/components/shared/ShareLinkDialog'
import { AnnotationDialog } from '@/components/shared/AnnotationDialog'
import { TagEditDialog, useTagEditor } from '@/components/shared/TagEditDialog'
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

  // Single-archive tag editor: the "item" is just the archive id; the dialog
  // pulls current tags from the cached meta payload.
  const tagEditor = useTagEditor<string>({
    getItemId: (id) => id,
    getInitialValue: () => (Array.isArray(meta?.tags) ? (meta?.tags ?? []).join(', ') : ''),
    onSave: (_id, tags) => {
      updateMeta.mutate({ tags })
    },
  })

  const blocks = useMemo<Block[]>(() => {
    const md = toText(data?.markdown)
    const sections = data?.sections
    if (Array.isArray(sections) && sections.length > 0) {
      const out: Block[] = []
      sections.forEach((section, idx) => {
        const title = toText((section as Record<string, unknown>)?.title) || toText((section as Record<string, unknown>)?.name)
        const content = toText((section as Record<string, unknown>)?.content) || toText((section as Record<string, unknown>)?.markdown)
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
      <div className="aurora-archive-screen flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="aurora-archive-screen flex flex-col items-center justify-center h-full p-6 text-center">
        <div className="aurora-archive-empty-icon h-16 w-16 rounded-full flex items-center justify-center mb-4">
          <BookOpen className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-medium mb-2">资料不存在</h3>
        <p className="text-muted-foreground mb-6">加载失败或已被删除</p>
        <Button asChild variant="outline">
          <Link to="/study-archives">返回学习档案</Link>
        </Button>
      </div>
    )
  }

  const title = `${toText(data?.subject)} ${toText(data?.topic)}`.trim() || `自学资料 #${String(archiveId)}`
  const isStarred = Boolean(meta?.starred)
  const isPinned = Boolean(meta?.pinned)
  const tags = Array.isArray(meta?.tags) ? meta.tags : []
  const archiveStats = [
    { label: '学科', value: toText(data?.subject) || '未标注' },
    { label: '主题', value: toText(data?.topic) || '自学资料' },
    { label: '内容块', value: `${blocks.length}` },
    { label: '标签', value: `${tags.length}` },
  ]

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
    <div className="aurora-archive-screen aurora-reading-theater h-full flex flex-col">
      <div className="aurora-archive-topbar border-b border-border p-4 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild className="rounded-full">
            <Link to="/study-archives" aria-label="返回">
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
            onClick={() => tagEditor.open(String(archiveId || ''))}
            aria-label="设置标签"
            title="设置标签"
          >
            <Tag className="h-4 w-4" />
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={createPlan}>
            <ListTodo className="h-4 w-4 mr-2" />
            学习计划
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              const params = new URLSearchParams()
              params.set('source_archive_id', String(archiveId || ''))
              params.set('topic', toText(data?.topic) || title)
              const subj = toText(data?.subject)
              if (subj) params.set('subject', subj)
              navigate(`/knowledge-videos?${params.toString()}`)
            }}
          >
            <Film className="h-4 w-4 mr-2" />
            知识视频
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
        <div className="aurora-archive-shell aurora-reading-shell space-y-4">
          <section className="aurora-archive-hero">
            <div className="text-center">
              <div className="aurora-archive-orb mx-auto mb-5">
                <BookOpen className="h-8 w-8" />
              </div>
              <div className="aurora-kicker justify-center">
                <Sparkles className="h-3.5 w-3.5" />
                Study Archive Bridge
              </div>
              <h1 className="mt-4 text-3xl font-semibold tracking-tight">{title}</h1>
              <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                这里沉淀自学资料的完整正文、章节结构、批注、标签和后续生成入口，可继续转为学习计划、知识视频或导出文档。
              </p>
            </div>

            <div className="aurora-archive-stat-grid mt-7">
              {archiveStats.map((item) => (
                <div key={item.label} className="aurora-archive-stat">
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>

            {(isStarred || isPinned || tags.length > 0 || q) && (
              <div className="aurora-archive-meta-strip mt-5">
                {isStarred && <span>已收藏</span>}
                {isPinned && <span>已置顶</span>}
                {tags.slice(0, 5).map((tag) => (
                  <span key={String(tag)}>{String(tag)}</span>
                ))}
                {!!q && <span>关键词：{q}</span>}
              </div>
            )}
          </section>

          {blocks.map((b) => {
            const isHit = hitBlockId === b.id
            return (
              <div
                key={b.id}
                id={b.id}
                data-hit={isHit ? 'true' : 'false'}
                className={cn(
                  'aurora-archive-block aurora-reading-block p-5',
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
                <div className="aurora-archive-body aurora-reading-body">
                  <Markdown markdown={b.markdown} />
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

      <TagEditDialog
        open={tagEditor.isOpen}
        itemTitle={title}
        value={tagEditor.value}
        onValueChange={tagEditor.setValue}
        onOpenChange={(open) => {
          if (!open) tagEditor.close()
        }}
        onSave={tagEditor.save}
      />
    </div>
  )
}
