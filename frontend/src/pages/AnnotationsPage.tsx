import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Loader2, Tag, CheckCircle2, Circle, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import * as annotationsApi from '@/api/annotations'

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

export default function AnnotationsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const initialTag = String(searchParams.get('tag') || '').trim()
  const [tag, setTag] = useState(initialTag)
  const [itemType, setItemType] = useState('')
  const [unresolvedOnly, setUnresolvedOnly] = useState(false)

  const { data: items = [], isLoading, error } = useQuery({
    queryKey: ['annotations', tag, itemType, unresolvedOnly],
    queryFn: () =>
      annotationsApi.listAnnotations({
        tag: (tag.trim() || (unresolvedOnly ? '疑问' : undefined)) || undefined,
        item_type: itemType.trim() || undefined,
        limit: 200,
      }),
  })

  const updateAnnotation = useMutation({
    mutationFn: (args: { id: number; tags: string[] }) => annotationsApi.updateAnnotation(args.id, { tags: args.tags }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['annotations'] }),
  })

  const filtered = useMemo(() => {
    if (!unresolvedOnly) return items
    return items.filter((a) => {
      const tags = Array.isArray(a.tags) ? a.tags.map((t) => String(t || '').trim()) : []
      const hasDoubt = tags.includes('疑问')
      const solved = tags.includes('已解决')
      return hasDoubt && !solved
    })
  }, [items, unresolvedOnly])
  const annotationStats = useMemo(() => {
    const unresolved = items.filter((a) => {
      const tags = Array.isArray(a.tags) ? a.tags.map((t) => String(t || '').trim()) : []
      return tags.includes('疑问') && !tags.includes('已解决')
    }).length
    const solved = items.filter((a) => {
      const tags = Array.isArray(a.tags) ? a.tags.map((t) => String(t || '').trim()) : []
      return tags.includes('已解决')
    }).length
    return [
      { label: '批注总数', value: `${items.length}` },
      { label: '当前列表', value: `${filtered.length}` },
      { label: '未解决', value: `${unresolved}` },
      { label: '已解决', value: `${solved}` },
    ]
  }, [filtered.length, items])

  const jump = (ann: annotationsApi.Annotation) => {
    const t = String(ann.item_type || '').trim()
    const id = String(ann.item_id || '').trim()
    const anchor = String(ann.anchor || '').trim()
    if (t === 'paper' && id) {
      navigate(`/papers/${id}${anchor ? `#${anchor}` : ''}`)
      return
    }
    if (t === 'study_archive' && id) {
      navigate(`/study-archives/${id}${anchor ? `#${anchor}` : ''}`)
      return
    }
    navigate('/tasks')
  }

  const exportAll = async () => {
    const all = await annotationsApi.exportAnnotations()
    downloadJson('annotations.json', { annotations: all })
  }

  return (
    <div className="aurora-annotations-screen h-full flex flex-col overflow-hidden">
      <div className="aurora-annotations-hero p-4 flex items-center justify-between sticky top-0 z-10">
        <div className="min-w-0">
          <div className="aurora-kicker">
            <Sparkles className="h-3.5 w-3.5" />
            Annotation Control Console
          </div>
          <div className="mt-2 flex items-center gap-2 font-semibold">
            <Tag className="h-4 w-4 text-primary" />
            批注与标注
          </div>
          <p className="mt-1 text-xs text-muted-foreground">集中处理试卷和学习资料中的批注，跟踪疑问、已解决状态，并回跳到原文位置。</p>
        </div>
        <div className="aurora-annotations-stat-grid">
          {annotationStats.map((item) => (
            <div key={item.label} className="aurora-annotations-stat">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
        <Button type="button" size="sm" variant="outline" onClick={exportAll}>
          <Download className="h-4 w-4 mr-2" />
          导出
        </Button>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
        <div className="aurora-annotations-filter p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Input className="aurora-annotations-input" value={tag} onChange={(e) => setTag(e.target.value)} placeholder="按标签过滤（例如：未解决）" />
            <Input className="aurora-annotations-input" value={itemType} onChange={(e) => setItemType(e.target.value)} placeholder="按类型过滤（paper / study_archive）" />
          </div>
          <label className="mt-3 inline-flex items-center gap-2 text-sm text-muted-foreground select-none">
            <input type="checkbox" checked={unresolvedOnly} onChange={(e) => setUnresolvedOnly(e.target.checked)} />
            仅看未解决疑问（标签：疑问 且不含 已解决）
          </label>
        </div>

        <ScrollArea className="flex-1">
          <div className="max-w-4xl mx-auto p-6 space-y-3">
            {error && <ErrorNotice error={error} />}
            {isLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                加载中…
              </div>
            )}
            {!isLoading && !error && filtered.length === 0 && (
              <Card className="aurora-annotations-empty p-6">
                <div className="text-sm text-muted-foreground">暂无批注。</div>
              </Card>
            )}

            {filtered.map((a) => {
              const tags = Array.isArray(a.tags) ? a.tags.map((t) => String(t || '').trim()).filter(Boolean) : []
              const isDoubt = tags.includes('疑问')
              const isSolved = tags.includes('已解决')
              const canToggleSolved = isDoubt

              return (
              <Card
                key={a.id}
                className="aurora-annotations-card p-4 cursor-pointer transition-colors"
                data-doubt={isDoubt ? 'true' : 'false'}
                data-solved={isSolved ? 'true' : 'false'}
                onClick={() => jump(a)}
              >
                <div className="text-xs text-muted-foreground font-mono">
                  {a.item_type}:{a.item_id} {a.anchor ? `#${a.anchor}` : ''}
                </div>

                {canToggleSolved && (
                  <div className="mt-2 flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={isSolved ? 'secondary' : 'outline'}
                      disabled={updateAnnotation.isPending}
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        const next = new Set(tags)
                        if (isSolved) next.delete('已解决')
                        else next.add('已解决')
                        updateAnnotation.mutate({ id: a.id, tags: Array.from(next) })
                      }}
                    >
                      {isSolved ? <CheckCircle2 className="h-3.5 w-3.5 mr-2" /> : <Circle className="h-3.5 w-3.5 mr-2" />}
                      {isSolved ? '已解决' : '标记已解决'}
                    </Button>
                  </div>
                )}

                {a.snippet && <div className="text-xs text-muted-foreground mt-2">{a.snippet}</div>}
                <div className="mt-2 whitespace-pre-wrap text-sm">{a.content}</div>
                {tags.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {tags.map((t) => (
                      <span key={t} className="aurora-annotations-tag text-[10px] px-1.5 py-0.5 rounded">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </Card>
            )})}
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
