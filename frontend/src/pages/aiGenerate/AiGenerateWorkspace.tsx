import { useMemo, useState } from 'react'
import { Loader2, Wand2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useSubjects } from '@/hooks/useSubjects'
import { useQuestionLibrary } from '@/pages/questionLibrary/hooks/useQuestionLibrary'
import { useQuestionLibraryTasks } from '@/pages/questionLibrary/hooks/useQuestionLibraryTasks'
import { QuestionLibraryCard } from '@/pages/questionLibrary/QuestionLibraryCard'
import { QuestionDetailDialog } from '@/pages/questionLibrary/QuestionDetailDialog'
import { RunPanel } from '@/pages/questionLibrary/RunPanel'

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

  return (
    <div className="h-full w-full flex flex-col overflow-hidden">
      <div className="px-6 py-4 border-b bg-background">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-lg font-semibold tracking-tight">AI 出题</div>
            <div className="text-xs text-muted-foreground">
              根据学科与知识点生成题目（含答案与解析），并自动入库。
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

            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="text-sm font-medium">最近 AI 题目</div>
                <div className="text-xs text-muted-foreground">共 {lib.total}</div>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={lib.refreshList} disabled={lib.listQuery.isFetching}>
                刷新
              </Button>
            </div>

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
                  />
                ))}
              </div>
            )}
          </div>
        </ScrollArea>
      </div>

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

