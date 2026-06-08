import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Trash2, Wand2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { RichTextarea } from '@/components/shared/RichTextarea'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import * as wrongbookApi from '@/api/wrongbook'

export function WrongbookListPanel() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [kp, setKp] = useState('')
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<wrongbookApi.WrongQuestion | null>(null)
  const [note, setNote] = useState('')
  const [mastery, setMastery] = useState('0')

  const { data: items = [], isLoading, error } = useQuery({
    queryKey: ['wrongbook', 'list', query, kp],
    queryFn: () =>
      wrongbookApi.listWrongbook({
        q: query.trim() || undefined,
        knowledge_point: kp.trim() || undefined,
        limit: 200,
      }),
  })

  const deleteMutation = useMutation({
    mutationFn: (questionId: string) => wrongbookApi.deleteWrongQuestion(questionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wrongbook'] })
    },
  })

  const upsertMutation = useMutation({
    mutationFn: (input: { question_id: string; note: string; mastery: number }) =>
      wrongbookApi.upsertWrongQuestion({
        question_id: input.question_id,
        note: input.note,
        mastery: input.mastery,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['wrongbook'] })
    },
  })

  const practiceMutation = useMutation({
    mutationFn: (input: { question_ids: string[]; paper_name: string }) =>
      wrongbookApi.createPracticePaper({
        question_ids: input.question_ids,
        paper_name: input.paper_name,
      }),
  })

  const selectedIds = useMemo(
    () =>
      Object.entries(selected)
        .filter(([, value]) => value)
        .map(([key]) => key),
    [selected],
  )

  const toggle = (qid: string) => {
    setSelected((prev) => ({ ...prev, [qid]: !prev[qid] }))
  }

  const openEdit = (it: wrongbookApi.WrongQuestion) => {
    setEditing(it)
    setNote(String(it.note || ''))
    setMastery(String(it.mastery ?? 0))
    setEditOpen(true)
  }

  const saveEdit = async () => {
    if (!editing) return
    const rawMastery = Number(mastery || 0)
    const nextMastery = Number.isFinite(rawMastery) ? Math.max(0, Math.min(100, rawMastery)) : 0
    await upsertMutation.mutateAsync({
      question_id: editing.question_id,
      note,
      mastery: nextMastery,
    })
    setEditOpen(false)
  }

  const createPractice = async () => {
    const ids = selectedIds.length > 0 ? selectedIds : items.map((item) => item.question_id)
    if (ids.length === 0) return
    const paperName = kp.trim() ? `错题练习：${kp.trim()}` : '错题练习卷'
    const res = await practiceMutation.mutateAsync({ question_ids: ids, paper_name: paperName })
    const paperId = Number(res?.paper_id || 0)
    if (paperId > 0) navigate(`/papers/${paperId}`)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="grid flex-1 grid-cols-1 gap-3 md:grid-cols-2">
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题目ID / 备注..." />
          <Input value={kp} onChange={(event) => setKp(event.target.value)} placeholder="按知识点过滤" />
        </div>
        <Button type="button" variant="outline" size="sm" onClick={createPractice} disabled={practiceMutation.isPending}>
          {practiceMutation.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Wand2 className="mr-2 h-4 w-4" />
          )}
          生成练习卷
        </Button>
      </div>

      {Boolean(error) && <ErrorNotice error={error} />}
      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          加载中...
        </div>
      )}

      {!isLoading && !error && items.length === 0 && (
        <Card className="p-6">
          <div className="text-sm text-muted-foreground">暂无错题。你可以在试卷详情页一键加入。</div>
        </Card>
      )}

      {items.map((it) => (
        <Card key={it.question_id} className="p-4">
          <div className="flex items-start justify-between gap-3">
            <label className="flex min-w-0 cursor-pointer items-start gap-3">
              <input
                type="checkbox"
                className="mt-1"
                checked={Boolean(selected[it.question_id])}
                onChange={() => toggle(it.question_id)}
              />
              <div className="min-w-0">
                <div className="break-all font-mono text-sm">{it.question_id}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {it.knowledge_point ? `知识点：${it.knowledge_point}` : '无知识点'} · 掌握度：{it.mastery}
                  {it.next_review_at ? ` · 下次复习：${new Date(it.next_review_at).toLocaleDateString('zh-CN')}` : ''}
                </div>
                {it.note && <div className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{it.note}</div>}
              </div>
            </label>
            <div className="flex shrink-0 items-center gap-2">
              <Button type="button" size="sm" variant="outline" onClick={() => openEdit(it)}>
                编辑
              </Button>
              <Button
                type="button"
                size="sm"
                variant="destructive"
                onClick={() => {
                  if (confirm('确定移出错题本吗？')) deleteMutation.mutate(it.question_id)
                }}
                disabled={deleteMutation.isPending}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                删除
              </Button>
            </div>
          </div>
        </Card>
      ))}

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>编辑错题</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {editing && (
              <div className="text-xs text-muted-foreground">
                题目ID：<span className="font-mono">{editing.question_id}</span>
              </div>
            )}
            <div className="space-y-1.5">
              <div className="text-sm font-medium">掌握度（0-100）</div>
              <Input value={mastery} onChange={(event) => setMastery(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <div className="text-sm font-medium">备注</div>
              <RichTextarea
                value={note}
                onChange={setNote}
                ariaLabel="备注"
                debounceMs={0}
                minHeight={112}
                maxHeight={260}
              />
            </div>
            <div className="flex items-center justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setEditOpen(false)}>
                取消
              </Button>
              <Button type="button" onClick={saveEdit} disabled={!editing || upsertMutation.isPending}>
                {upsertMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : '保存'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
