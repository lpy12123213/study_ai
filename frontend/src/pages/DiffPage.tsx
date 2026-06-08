import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { diffLines } from 'diff'
import { ArrowRightLeft, Loader2, PlusSquare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { useNotificationStore } from '@/stores/useNotificationStore'
import * as papersApi from '@/api/papers'
import * as studyArchivesApi from '@/api/studyArchives'
import { isRecord, readStringFrom, readNumber } from '@/lib/record'
import type { Paper } from '@/types'
import type { StudyArchive } from '@/api/studyArchives'

type DiffType = 'paper' | 'study_archive'

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function questionIdsFromPaper(paper: Paper | undefined): string[] {
  if (!paper) return []
  return (paper.questions || [])
    .map((q) => readStringFrom(q, ['questionId', 'question_id']))
    .filter((id): id is string => Boolean(id))
}

export default function DiffPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const initialType = (searchParams.get('type') as DiffType) || 'paper'
  const [type, setType] = useState<DiffType>(initialType)
  const [aId, setAId] = useState(String(searchParams.get('a') || '').trim())
  const [bId, setBId] = useState(String(searchParams.get('b') || '').trim())
  const addToast = useNotificationStore((s) => s.addToast)

  const canCompare = Boolean(type && aId && bId)

  const queryKey = ['diff', type, aId, bId]
  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: async () => {
      if (type === 'paper') {
        const [a, b] = await Promise.all([papersApi.getPaper(aId), papersApi.getPaper(bId)])
        return { a, b }
      }
      const [a, b] = await Promise.all([studyArchivesApi.getStudyArchive(aId), studyArchivesApi.getStudyArchive(bId)])
      return { a, b }
    },
    enabled: canCompare,
  })

  const paperDiff = useMemo(() => {
    if (!data || type !== 'paper') return null
    const a = data.a as Paper
    const b = data.b as Paper
    const aIds = questionIdsFromPaper(a)
    const bIds = questionIdsFromPaper(b)
    const setA = new Set(aIds)
    const setB = new Set(bIds)
    const removedAll = aIds.filter((id) => !setB.has(id))
    const addedAll = bIds.filter((id) => !setA.has(id))
    const replaced: Array<{ order: number; from: string; to: string }> = []
    const max = Math.max(aIds.length, bIds.length)
    for (let i = 0; i < max; i++) {
      const from = aIds[i]
      const to = bIds[i]
      if (from && to && from !== to && !setB.has(from) && !setA.has(to)) replaced.push({ order: i + 1, from, to })
    }
    const replacedFrom = new Set(replaced.map((item) => item.from))
    const replacedTo = new Set(replaced.map((item) => item.to))
    const removed = removedAll.filter((id) => !replacedFrom.has(id))
    const added = addedAll.filter((id) => !replacedTo.has(id))
    return { a, b, removed, added, replaced, aIds, bIds }
  }, [data, type])

  const textDiff = useMemo(() => {
    if (!data || type !== 'study_archive') return null
    const a = data.a as StudyArchive
    const b = data.b as StudyArchive
    const parts = diffLines(text(a?.markdown), text(b?.markdown))
    return { a, b, parts }
  }, [data, type])

  const clonePaper = useMutation({
    mutationFn: async (paper: Paper) => {
      const qids = questionIdsFromPaper(paper)
      const name = `${String(paper?.name || '试卷')}-复制-${new Date().toISOString().slice(0, 10)}`
      return await papersApi.createPaper({ name, questionIds: qids })
    },
    onSuccess: (res) => {
      const pid = Number(res?.paperId || (res as any)?.id || 0)
      if (pid > 0) navigate(`/papers/${pid}`)
      else addToast({ title: '复制试卷失败：缺少新试卷 ID', status: 'failed' })
    },
    onError: () => addToast({ title: '复制试卷失败', status: 'failed' }),
  })

  const cloneArchive = useMutation({
    mutationFn: async (archive: StudyArchive) => {
      const id = Number(archive?.id || 0)
      if (id > 0) {
        return await studyArchivesApi.cloneStudyArchive(id)
      }
      return await studyArchivesApi.createStudyArchive({
        subject: String(archive?.subject || '').trim(),
        topic: String(archive?.topic || '').trim() || '自学资料',
        preset: String(archive?.preset || '').trim(),
        requirements: String(archive?.requirements || '').trim(),
        markdown: String(archive?.markdown || ''),
        sections: Array.isArray(archive?.sections) ? archive.sections : [],
      })
    },
    onSuccess: (res) => {
      const id = readNumber(isRecord(res) ? res : {}, 'id', 0)
      if (id > 0) navigate(`/study-archives/${id}`)
      else addToast({ title: '复制资料失败：缺少新资料 ID', status: 'failed' })
    },
    onError: () => addToast({ title: '复制资料失败', status: 'failed' }),
  })

  const applyParams = () => {
    setSearchParams({ type, a: aId, b: bId })
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-background">
      <div className="border-b border-border p-4 flex items-center justify-between sticky top-0 bg-background/80 backdrop-blur-sm z-10">
        <div className="flex items-center gap-2 font-semibold">
          <ArrowRightLeft className="h-4 w-4 text-primary" />
          对比与差异
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto p-6">
        <div className="max-w-5xl mx-auto space-y-4">
          <Card className="p-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <Select value={type} onValueChange={(v) => setType(v as DiffType)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="paper">试卷</SelectItem>
                  <SelectItem value="study_archive">自学资料</SelectItem>
                </SelectContent>
              </Select>
              <Input value={aId} onChange={(e) => setAId(e.target.value)} placeholder="版本 A 的 ID" />
              <Input value={bId} onChange={(e) => setBId(e.target.value)} placeholder="版本 B 的 ID" />
              <Button type="button" onClick={applyParams} disabled={!canCompare}>
                开始对比
              </Button>
            </div>
          </Card>

          {error && <ErrorNotice error={error} />}
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          )}

          {paperDiff && (
            <>
              <Card className="p-4">
                <div className="font-medium">试卷差异</div>
                <div className="text-xs text-muted-foreground mt-1">
                  A: #{aId} · B: #{bId}
                </div>
                <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
                  <Card className="p-3">
                    <div className="text-xs text-muted-foreground">新增</div>
                    <div className="mt-2 text-sm font-mono whitespace-pre-wrap break-words">{paperDiff.added.join('\n') || '-'}</div>
                  </Card>
                  <Card className="p-3">
                    <div className="text-xs text-muted-foreground">删除</div>
                    <div className="mt-2 text-sm font-mono whitespace-pre-wrap break-words">{paperDiff.removed.join('\n') || '-'}</div>
                  </Card>
                  <Card className="p-3">
                    <div className="text-xs text-muted-foreground">替换（按题号）</div>
                    <div className="mt-2 text-sm font-mono whitespace-pre-wrap break-words">
                      {paperDiff.replaced.length === 0
                        ? '-'
                        : paperDiff.replaced.map((r) => `${r.order}: ${r.from} → ${r.to}`).join('\n')}
                    </div>
                  </Card>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <Button type="button" variant="outline" onClick={() => navigate(`/papers/${aId}`)}>
                    打开 A
                  </Button>
                  <Button type="button" variant="outline" onClick={() => navigate(`/papers/${bId}`)}>
                    打开 B
                  </Button>
                  <Button type="button" variant="outline" onClick={() => clonePaper.mutate(paperDiff.a)} disabled={clonePaper.isPending}>
                    {clonePaper.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <PlusSquare className="h-4 w-4 mr-2" />}
                    复制为新试卷（A）
                  </Button>
                  <Button type="button" variant="outline" onClick={() => clonePaper.mutate(paperDiff.b)} disabled={clonePaper.isPending}>
                    {clonePaper.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <PlusSquare className="h-4 w-4 mr-2" />}
                    复制为新试卷（B）
                  </Button>
                </div>
              </Card>
            </>
          )}

          {textDiff && (
            <Card className="p-4">
              <div className="font-medium">自学资料差异（按行）</div>
              <div className="text-xs text-muted-foreground mt-1">
                A: #{aId} · B: #{bId}
              </div>
              <pre className="mt-4 max-h-[70vh] overflow-auto rounded-md border bg-muted/20 p-3 text-xs leading-5">
                {textDiff.parts.map((p, idx) => {
                  const cls = p.added
                    ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                    : p.removed
                      ? 'bg-destructive/15 text-destructive'
                      : ''
                  return (
                    <span key={idx} className={cls}>
                      {p.value}
                    </span>
                  )
                })}
              </pre>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button type="button" variant="outline" onClick={() => navigate(`/study-archives/${aId}`)}>
                  打开 A
                </Button>
                <Button type="button" variant="outline" onClick={() => navigate(`/study-archives/${bId}`)}>
                  打开 B
                </Button>
                <Button type="button" variant="outline" onClick={() => cloneArchive.mutate(textDiff.a)} disabled={cloneArchive.isPending}>
                  {cloneArchive.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <PlusSquare className="h-4 w-4 mr-2" />}
                  复制为新资料（A）
                </Button>
                <Button type="button" variant="outline" onClick={() => cloneArchive.mutate(textDiff.b)} disabled={cloneArchive.isPending}>
                  {cloneArchive.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <PlusSquare className="h-4 w-4 mr-2" />}
                  复制为新资料（B）
                </Button>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
