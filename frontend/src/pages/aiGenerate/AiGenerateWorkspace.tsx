import { useEffect, useMemo, useState } from 'react'
import { Loader2, Wand2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useSubjects } from '@/hooks/useSubjects'
import { bulkDeleteQuestionLibraryItems, commitQuestionLibraryPreview, discardQuestionLibraryPreview, type QuestionLibraryDraftQuestion } from '@/api/questionLibrary'
import { useQuestionLibrary } from '@/pages/questionLibrary/hooks/useQuestionLibrary'
import { useQuestionLibraryTasks } from '@/pages/questionLibrary/hooks/useQuestionLibraryTasks'
import { QuestionLibraryCard } from '@/pages/questionLibrary/QuestionLibraryCard'
import { QuestionDetailDialog } from '@/pages/questionLibrary/QuestionDetailDialog'
import { QuestionBar } from '@/pages/questionLibrary/QuestionBar'
import { RunPanel } from '@/pages/questionLibrary/RunPanel'
import { useToastStore } from '@/stores/useToastStore'

const DIFFICULTY_ANY = '__any__'

export function AiGenerateWorkspace() {
  const { data: subjects } = useSubjects()

  const lib = useQuestionLibrary({
    initialFilters: {
      origin: 'ai',
      hidden: '0',
      sort: 'updated_at',
      order: 'desc',
    },
  })

  const tasks = useQuestionLibraryTasks({
    filters: lib.filters,
    restoreLatestPreview: true,
    onDone: async () => {
      await lib.refreshList()
      await lib.refreshDetail()
    },
  })

  const [topic, setTopic] = useState('')
  const [difficulty, setDifficulty] = useState(DIFFICULTY_ANY)
  const [questionType, setQuestionType] = useState('')
  const [count, setCount] = useState('5')
  const [useStudyArchive, setUseStudyArchive] = useState(true)

  const [detailOpen, setDetailOpen] = useState(false)
  const [bulkMode, setBulkMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Record<string, boolean>>({})
  const [isBulkDeleting, setIsBulkDeleting] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)

  const pushToast = useToastStore((s) => s.pushToast)

  const [draftQuestions, setDraftQuestions] = useState<QuestionLibraryDraftQuestion[]>([])
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [isCommitting, setIsCommitting] = useState(false)
  const [isDiscarding, setIsDiscarding] = useState(false)

  const previewId = String(tasks.draftPreview?.previewId || '').trim()

  useEffect(() => {
    if (!tasks.draftPreview) {
      setDraftQuestions([])
      setPreviewError(null)
      return
    }
    setDraftQuestions(
      (tasks.draftPreview.draftQuestions || []).map((q) => ({
        ...q,
        keep: q.keep === false ? false : true,
      }))
    )
    setPreviewError(null)
  }, [tasks.draftPreview])

  const selectedCount = useMemo(() => {
    return Object.values(selectedIds).filter(Boolean).length
  }, [selectedIds])

  const canGenerate = useMemo(() => {
    if (!lib.filters.subject.trim()) return false
    if (!topic.trim()) return false
    return true
  }, [lib.filters.subject, topic])

  const run = () => {
    if (!canGenerate) return

    const n = Number(count)
    const finalCount = Number.isFinite(n) ? Math.max(1, Math.min(10, Math.floor(n))) : 5

    tasks.runGenerate({
      subject: lib.filters.subject,
      topic: topic.trim(),
      difficulty: difficulty === DIFFICULTY_ANY ? '' : difficulty,
      question_type: questionType.trim(),
      count: finalCount,
      use_study_archive: Boolean(useStudyArchive),
    })
  }

  const openDetail = (qid: string) => {
    lib.setSelectedId(qid)
    setDetailOpen(true)
  }

  const toggleBulkMode = () => {
    setBulkError(null)
    setSelectedIds({})
    setBulkMode((v) => !v)
  }

  const toggleSelected = (qid: string) => {
    const id = String(qid || '').trim()
    if (!id) return
    setSelectedIds((prev) => {
      const next = { ...prev }
      if (next[id]) delete next[id]
      else next[id] = true
      return next
    })
  }

  const selectAllOnPage = () => {
    setBulkError(null)
    setSelectedIds(() => {
      const next: Record<string, boolean> = {}
      for (const it of lib.items) {
        const id = String(it.question_id || '').trim()
        if (!id) continue
        next[id] = true
      }
      return next
    })
  }

  const clearSelection = () => {
    setBulkError(null)
    setSelectedIds({})
  }

  const deleteSelected = async () => {
    if (isBulkDeleting) return
    const ids = Object.entries(selectedIds)
      .filter(([, v]) => v)
      .map(([k]) => k)
    if (ids.length === 0) return

    const ok = confirm(`确定要删除选中的 ${ids.length} 道题吗？此操作不可恢复。`)
    if (!ok) return

    setIsBulkDeleting(true)
    setBulkError(null)
    try {
      await bulkDeleteQuestionLibraryItems(ids)
      const deletedSet = new Set(ids)
      if (deletedSet.has(String(lib.selectedId || '').trim())) {
        lib.setSelectedId('')
        setDetailOpen(false)
      }
      clearSelection()
      await lib.refreshList()
      await lib.refreshDetail()
    } catch (err: any) {
      setBulkError(err?.message || '批量删除失败')
    } finally {
      setIsBulkDeleting(false)
    }
  }

  const commitPreview = async () => {
    if (!previewId) return
    if (isCommitting) return
    const kept = draftQuestions.filter((q) => q.keep)
    if (kept.length === 0) {
      setPreviewError('请至少选择 1 道题入库')
      return
    }

    setIsCommitting(true)
    setPreviewError(null)
    try {
      const res = await commitQuestionLibraryPreview(previewId, draftQuestions)
      pushToast({
        id: `ql-preview-commit-${previewId}`,
        title: `已入库 ${Number(res.inserted || 0)} 道题`,
        status: 'completed',
      })
      tasks.clearDraftPreview()
      await lib.refreshList()
      await lib.refreshDetail()
    } catch (err: any) {
      setPreviewError(err?.message || '入库失败')
      pushToast({ id: `ql-preview-commit-failed-${previewId}`, title: '入库失败', status: 'failed' })
    } finally {
      setIsCommitting(false)
    }
  }

  const discardPreview = async () => {
    if (!previewId) return
    if (isDiscarding) return
    const ok = confirm('确定要丢弃本次生成的草稿吗？')
    if (!ok) return

    setIsDiscarding(true)
    setPreviewError(null)
    try {
      await discardQuestionLibraryPreview(previewId)
      pushToast({ id: `ql-preview-discard-${previewId}`, title: '草稿已丢弃', status: 'completed' })
      tasks.clearDraftPreview()
    } catch (err: any) {
      setPreviewError(err?.message || '丢弃失败')
      pushToast({ id: `ql-preview-discard-failed-${previewId}`, title: '丢弃失败', status: 'failed' })
    } finally {
      setIsDiscarding(false)
    }
  }

  return (
    <div className="h-full w-full flex flex-col overflow-hidden">
      <div className="px-6 py-4 border-b bg-background">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-lg font-semibold tracking-tight">AI 出题</div>
            <div className="text-xs text-muted-foreground">
              根据学科与知识点生成题目（含答案与解析）；生成后进入预览审核，通过后再入库。
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="p-6 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">生成配置</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
                  <div className="md:col-span-3">
                    <div className="text-xs text-muted-foreground mb-2">学科</div>
                    <Select value={lib.filters.subject} onValueChange={lib.setSubject}>
                      <SelectTrigger className="h-9">
                        <SelectValue placeholder="选择学科" />
                      </SelectTrigger>
                      <SelectContent>
                        {(subjects || []).map((s) => (
                          <SelectItem key={s.code} value={s.code}>
                            {s.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="md:col-span-5">
                    <div className="text-xs text-muted-foreground mb-2">主题 / 知识点</div>
                    <Input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="例如：函数 单调性" className="h-9" />
                  </div>
                  <div className="md:col-span-2">
                    <div className="text-xs text-muted-foreground mb-2">难度</div>
                    <Select value={difficulty} onValueChange={setDifficulty}>
                      <SelectTrigger className="h-9">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={DIFFICULTY_ANY}>不限</SelectItem>
                        <SelectItem value="简单">简单</SelectItem>
                        <SelectItem value="中等">中等</SelectItem>
                        <SelectItem value="困难">困难</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="md:col-span-2">
                    <div className="text-xs text-muted-foreground mb-2">数量</div>
                    <Input value={count} onChange={(e) => setCount(e.target.value)} placeholder="5" className="h-9" />
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
                  <div className="md:col-span-8">
                    <div className="text-xs text-muted-foreground mb-2">题型（可选）</div>
                    <Input
                      value={questionType}
                      onChange={(e) => setQuestionType(e.target.value)}
                      placeholder="例如：选择题 / 填空题 / 解答题"
                      className="h-9"
                    />
                  </div>
                  <div className="md:col-span-4">
                    <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium">使用自学资料</div>
                        <div className="text-xs text-muted-foreground">从 StudyArchive 提取上下文，提高生成质量</div>
                      </div>
                      <Switch checked={useStudyArchive} onCheckedChange={(v: boolean) => setUseStudyArchive(Boolean(v))} />
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <Button type="button" onClick={run} disabled={!canGenerate}>
                    <Wand2 className="h-4 w-4 mr-2" />
                    开始生成
                  </Button>
                  {tasks.preferredTask?.status === 'running' && (
                    <div className="text-xs text-muted-foreground flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      生成中…
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {tasks.draftPreview && (
              <Card className="border-primary/20">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <CardTitle className="text-base">待审核草稿</CardTitle>
                      <div className="text-xs text-muted-foreground mt-1">
                        {tasks.draftPreview.subject} · {tasks.draftPreview.topic} · {tasks.draftPreview.count} 题 · {tasks.draftPreview.previewId}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={isCommitting || isDiscarding}
                        onClick={discardPreview}
                      >
                        {isDiscarding ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                        丢弃
                      </Button>
                      <Button
                        type="button"
                        variant="default"
                        size="sm"
                        disabled={isCommitting || isDiscarding || draftQuestions.filter((q) => q.keep).length === 0}
                        onClick={commitPreview}
                      >
                        {isCommitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                        入库选中 ({draftQuestions.filter((q) => q.keep).length})
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  {previewError && <div className="text-sm text-destructive">{previewError}</div>}

                  <div className="space-y-4">
                    {draftQuestions.map((q, idx) => (
                      <div key={q.question_id} className="rounded-lg border p-4 space-y-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-medium">
                            #{idx + 1} · {q.question_id}
                          </div>
                          <div className="flex items-center gap-2">
                            <div className="text-xs text-muted-foreground select-none">{q.keep ? '保留' : '丢弃'}</div>
                            <Switch
                              checked={Boolean(q.keep)}
                              onCheckedChange={(v: boolean) => {
                                const keep = Boolean(v)
                                setDraftQuestions((prev) =>
                                  prev.map((it) => (it.question_id === q.question_id ? { ...it, keep } : it))
                                )
                              }}
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                          <div className="md:col-span-3">
                            <div className="text-xs text-muted-foreground mb-2">题干</div>
                            <Textarea
                              value={q.stem}
                              onChange={(e) => {
                                const stem = e.target.value
                                setDraftQuestions((prev) =>
                                  prev.map((it) => (it.question_id === q.question_id ? { ...it, stem } : it))
                                )
                              }}
                              className="min-h-[92px]"
                            />
                          </div>
                          <div>
                            <div className="text-xs text-muted-foreground mb-2">答案</div>
                            <Textarea
                              value={q.answer}
                              onChange={(e) => {
                                const answer = e.target.value
                                setDraftQuestions((prev) =>
                                  prev.map((it) => (it.question_id === q.question_id ? { ...it, answer } : it))
                                )
                              }}
                              className="min-h-[92px]"
                            />
                          </div>
                          <div className="md:col-span-2">
                            <div className="text-xs text-muted-foreground mb-2">解析</div>
                            <Textarea
                              value={q.analysis}
                              onChange={(e) => {
                                const analysis = e.target.value
                                setDraftQuestions((prev) =>
                                  prev.map((it) => (it.question_id === q.question_id ? { ...it, analysis } : it))
                                )
                              }}
                              className="min-h-[92px]"
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="text-sm font-medium">最近 AI 题目</div>
                <div className="text-xs text-muted-foreground">共 {lib.total}</div>
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" variant={bulkMode ? 'secondary' : 'outline'} size="sm" onClick={toggleBulkMode}>
                  批量删除
                </Button>
                {bulkMode && (
                  <>
                    <Button type="button" variant="ghost" size="sm" onClick={selectAllOnPage} disabled={lib.items.length === 0}>
                      全选本页
                    </Button>
                    <Button type="button" variant="ghost" size="sm" onClick={clearSelection} disabled={selectedCount === 0}>
                      清空
                    </Button>
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      onClick={deleteSelected}
                      disabled={selectedCount === 0 || isBulkDeleting}
                      className="gap-2"
                    >
                      {isBulkDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                      删除 ({selectedCount})
                    </Button>
                  </>
                )}
                <Button type="button" variant="outline" size="sm" onClick={lib.refreshList} disabled={lib.listQuery.isFetching}>
                  刷新
                </Button>
              </div>
            </div>

            {bulkError && (
              <div className="text-sm text-destructive">{bulkError}</div>
            )}

            {lib.listQuery.isLoading ? (
              <div className="flex items-center justify-center text-muted-foreground text-sm py-10">
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                加载中…
              </div>
            ) : lib.listQuery.error ? (
              <div className="text-destructive text-sm py-10 text-center">
                {(lib.listQuery.error as any)?.message || '加载失败'}
              </div>
            ) : lib.items.length === 0 ? (
              <div className="text-muted-foreground text-sm py-10 text-center">暂无 AI 题目</div>
            ) : (
              <div className="space-y-4">
                {lib.items.map((it) => (
                  <QuestionLibraryCard
                    key={it.question_id}
                    item={it}
                    onOpenDetail={openDetail}
                    onSearchSimilar={(q) => lib.setQuery(q)}
                    onMutated={async () => {
                      await lib.refreshList()
                      await lib.refreshDetail()
                    }}
                    bulk={
                      bulkMode
                        ? {
                            enabled: true,
                            selected: Boolean(selectedIds[String(it.question_id || '').trim()]),
                            onToggle: () => toggleSelected(String(it.question_id || '').trim()),
                          }
                        : undefined
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </ScrollArea>
      </div>

      <QuestionBar />
      <RunPanel task={tasks.preferredTask} />

      <QuestionDetailDialog
        open={detailOpen}
        onOpenChange={(open) => {
          setDetailOpen(open)
          if (!open) lib.setSelectedId('')
        }}
        selectedId={lib.selectedId}
        listItem={lib.selectedItem}
        detail={lib.detail}
        isLoading={lib.detailQuery.isLoading}
        error={lib.detailQuery.error as any}
        onMutated={async () => {
          await lib.refreshList()
          await lib.refreshDetail()
        }}
      />
    </div>
  )
}
