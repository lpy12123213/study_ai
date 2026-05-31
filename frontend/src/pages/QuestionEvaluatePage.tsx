import { useMemo, useState } from 'react'
import { Loader2, Search, Wand2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RichTextarea } from '@/components/shared/RichTextarea'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { shouldSubmitOnEnter } from '@/lib/keyboard'
import { cn } from '@/lib/utils'
import { useSubjects } from '@/hooks/useSubjects'
import * as questionEvaluateApi from '@/api/questionEvaluate'

function verdictBadgeVariant(verdict: string): 'default' | 'secondary' | 'destructive' {
  if (verdict === '好题') return 'default'
  if (verdict === '普通题') return 'secondary'
  if (verdict === '差题') return 'destructive'
  return 'secondary'
}

function scoreClass(score: number): string {
  if (score >= 80) return 'text-emerald-600'
  if (score >= 60) return 'text-amber-600'
  return 'text-rose-600'
}

// Radix Select reserves the empty string value for clearing the selection.
const DIFFICULTY_ANY = '__any__'

export default function QuestionEvaluatePage() {
  const { data: subjects } = useSubjects()

  const [subject, setSubject] = useState<string>('高中数学')
  const [query, setQuery] = useState<string>('')
  const [difficulty, setDifficulty] = useState<string>(DIFFICULTY_ANY)

  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [searchResults, setSearchResults] = useState<questionEvaluateApi.QuestionEvaluateQuestion[]>([])

  const [selectedIds, setSelectedIds] = useState<Record<string, boolean>>({})

  const [requirements, setRequirements] = useState<string>('')
  const [isEvaluating, setIsEvaluating] = useState(false)
  const [evalError, setEvalError] = useState<string | null>(null)
  const [evalResults, setEvalResults] = useState<questionEvaluateApi.QuestionEvaluateResult[]>([])

  const selectedQuestions = useMemo(() => {
    const set = new Set(Object.entries(selectedIds).filter(([, v]) => v).map(([k]) => k))
    return searchResults.filter((q) => set.has(q.questionId))
  }, [searchResults, selectedIds])

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const selectAll = () => {
    const next: Record<string, boolean> = {}
    for (const q of searchResults) next[q.questionId] = true
    setSelectedIds(next)
  }

  const clearSelection = () => {
    setSelectedIds({})
  }

  const doSearch = async () => {
    const q = query.trim()
    if (!q) return

    setIsSearching(true)
    setSearchError(null)
    setEvalResults([])
    setEvalError(null)

    try {
      const res = await questionEvaluateApi.searchQuestions({
        query: q,
        subject,
        difficulty: difficulty && difficulty !== DIFFICULTY_ANY ? difficulty : undefined,
        limit: 20,
        maxPages: 2,
        minQualityScore: 0,
      })

      if (!res.success) {
        setSearchError(res.error || '搜索失败')
        setSearchResults([])
        setSelectedIds({})
        return
      }

      setSearchResults(res.questions)
      setSelectedIds({})
    } catch (err: any) {
      setSearchError(err?.message || '搜索失败')
      setSearchResults([])
      setSelectedIds({})
    } finally {
      setIsSearching(false)
    }
  }

  const doEvaluate = async () => {
    if (selectedQuestions.length === 0) return

    setIsEvaluating(true)
    setEvalError(null)
    try {
      const res = await questionEvaluateApi.evaluateQuestions({
        subject,
        requirements,
        questions: selectedQuestions,
      })
      setEvalResults(res.results)
    } catch (err: any) {
      setEvalError(err?.message || '鉴别失败')
      setEvalResults([])
    } finally {
      setIsEvaluating(false)
    }
  }

  const orderedEval = useMemo(() => {
    const items = [...evalResults]
    items.sort((a, b) => (b.overallScore || 0) - (a.overallScore || 0))
    return items
  }, [evalResults])

  return (
    <div className="h-full p-6 overflow-hidden">
      <div className="h-full max-w-6xl mx-auto flex flex-col gap-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight mb-1">好题鉴别</h1>
          <p className="text-muted-foreground text-sm">
            搜索题目后批量选择，使用 AI 从多维度评估题目质量。
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">搜索</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
              <div className="md:col-span-3">
                <label className="text-xs text-muted-foreground">学科</label>
                <Select value={subject} onValueChange={(v) => setSubject(v)}>
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder="选择学科" />
                  </SelectTrigger>
                  <SelectContent>
                    {(subjects || [])
                      .filter((s) => (s.code || '').trim().length > 0)
                      .map((s) => (
                        <SelectItem key={s.id} value={s.code}>
                          {s.name}
                        </SelectItem>
                      ))}
                    {(!subjects || subjects.length === 0) && (
                      <SelectItem value="高中数学">高中数学</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>

              <div className="md:col-span-6">
                <label className="text-xs text-muted-foreground">关键词</label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="输入关键词（如：函数 单调性）"
                    className="pl-9 h-9"
                    onKeyDown={(e) => {
                      if (shouldSubmitOnEnter(e)) doSearch()
                    }}
                  />
                </div>
              </div>

              <div className="md:col-span-2">
                <label className="text-xs text-muted-foreground">难度</label>
                <Select value={difficulty} onValueChange={(v) => setDifficulty(v === DIFFICULTY_ANY ? '' : v)}>
                  <SelectTrigger className="h-9">
                    <SelectValue placeholder="不限" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DIFFICULTY_ANY}>不限</SelectItem>
                    <SelectItem value="简单">简单</SelectItem>
                    <SelectItem value="中等">中等</SelectItem>
                    <SelectItem value="困难">困难</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="md:col-span-1 flex justify-end">
                <Button onClick={doSearch} disabled={isSearching || !query.trim()} className="gap-2">
                  {isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  搜索
                </Button>
              </div>
            </div>

            {searchError && (
              <div className="mt-3 text-sm text-destructive">{searchError}</div>
            )}
          </CardContent>
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 flex-1 min-h-0">
          <Card className="flex flex-col min-h-0">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-base">搜索结果</CardTitle>
                <div className="flex items-center gap-2">
                  <Button variant="secondary" size="sm" onClick={selectAll} disabled={searchResults.length === 0}>
                    全选
                  </Button>
                  <Button variant="ghost" size="sm" onClick={clearSelection} disabled={Object.keys(selectedIds).length === 0}>
                    清空
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="flex-1 min-h-0">
              {searchResults.length === 0 ? (
                <div className="text-sm text-muted-foreground py-10 text-center">暂无结果</div>
              ) : (
                <ScrollArea className="h-full pr-2">
                  <div className="space-y-2">
                    {searchResults.map((q) => {
                      const checked = Boolean(selectedIds[q.questionId])
                      return (
                        <button
                          key={q.questionId}
                          onClick={() => toggleSelected(q.questionId)}
                          className={cn(
                            'w-full text-left rounded-lg border p-3 transition-colors',
                            checked ? 'bg-accent border-accent' : 'hover:bg-muted/40',
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="font-medium text-sm truncate">题目 {q.questionId}</div>
                              <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                {q.stem || '（无题干）'}
                              </div>
                              <div className="mt-2 flex flex-wrap gap-2">
                                {q.type && <Badge variant="outline" className="text-[11px]">{q.type}</Badge>}
                                {q.difficulty && <Badge variant="secondary" className="text-[11px]">{q.difficulty}</Badge>}
                                {typeof q.qualityScore === 'number' && (
                                  <Badge variant="outline" className="text-[11px]">质量:{q.qualityScore}</Badge>
                                )}
                              </div>
                            </div>
                            <div className={cn('text-xs font-medium', checked ? 'text-foreground' : 'text-muted-foreground')}>
                              {checked ? '已选' : '未选'}
                            </div>
                          </div>
                        </button>
                      )
                    })}
                  </div>
                </ScrollArea>
              )}
            </CardContent>
          </Card>

          <Card className="flex flex-col min-h-0">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-base">鉴别结果</CardTitle>
                <Button
                  onClick={doEvaluate}
                  disabled={isEvaluating || selectedQuestions.length === 0}
                  className="gap-2"
                  size="sm"
                >
                  {isEvaluating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                  鉴别 ({selectedQuestions.length})
                </Button>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 flex-1 min-h-0">
              <div>
                <label className="text-xs text-muted-foreground">额外要求（可选）</label>
                <RichTextarea
                  value={requirements}
                  onChange={setRequirements}
                  placeholder="例如：偏向区分度强、题干表述严谨、避免怪题偏题"
                  ariaLabel="额外要求"
                  debounceMs={0}
                  minHeight={90}
                  maxHeight={220}
                />
              </div>

              {evalError && <div className="text-sm text-destructive">{evalError}</div>}

              <div className="flex-1 min-h-0">
                {orderedEval.length === 0 ? (
                  <div className="text-sm text-muted-foreground py-10 text-center">暂无结果</div>
                ) : (
                  <ScrollArea className="h-full pr-2">
                    <div className="space-y-3">
                      {orderedEval.map((r) => (
                        <div key={r.questionId} className="rounded-lg border p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <div className="font-medium text-sm">题目 {r.questionId}</div>
                                <Badge variant={verdictBadgeVariant(r.verdict)} className="text-[11px]">
                                  {r.verdict || '结果'}
                                </Badge>
                              </div>
                              <div className={cn('text-xs mt-1', scoreClass(r.overallScore))}>
                                总分：{r.overallScore}
                              </div>
                            </div>
                          </div>

                          {r.dimensions?.length > 0 && (
                            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
                              {r.dimensions.map((d) => (
                                <div key={d.name} className="rounded-md bg-muted/30 p-2">
                                  <div className="flex items-center justify-between text-xs">
                                    <span className="text-muted-foreground">{d.name}</span>
                                    <span className="font-medium">{d.score}/10</span>
                                  </div>
                                  {d.comment && (
                                    <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                      {d.comment}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}

                          {(r.highlights?.length > 0 || r.issues?.length > 0) && (
                            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                              <div>
                                <div className="text-xs font-medium mb-1">亮点</div>
                                <div className="text-xs text-muted-foreground space-y-1">
                                  {(r.highlights || []).map((t, idx) => (
                                    <div key={idx} className="line-clamp-2">- {t}</div>
                                  ))}
                                </div>
                              </div>
                              <div>
                                <div className="text-xs font-medium mb-1">问题</div>
                                <div className="text-xs text-muted-foreground space-y-1">
                                  {(r.issues || []).map((t, idx) => (
                                    <div key={idx} className="line-clamp-2">- {t}</div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          )}

                          {r.summary && (
                            <div className="mt-3 text-xs text-muted-foreground whitespace-pre-wrap">
                              {r.summary}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </ScrollArea>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
