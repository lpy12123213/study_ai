import { useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft,
  ExternalLink,
  FileText,
  Link2,
  Loader2,
  Printer,
  BarChart3
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { usePaper, usePaperDownloadLink } from '@/hooks/usePapers'
import { formatDate } from '@/lib/utils'

export default function PaperDetailPage() {
  const { paperId } = useParams<{ paperId: string }>()
  const { data: paper, isLoading, error } = usePaper(paperId)
  const {
    mutate: loadDownloadLinks,
    data: download,
    isPending: isLoadingLinks,
  } = usePaperDownloadLink()

  const handlePrint = () => {
    window.print()
  }

  const questionsByType = useMemo(() => {
    if (!paper) return {}
    const groups: Record<string, typeof paper.questions> = {}
    for (const q of paper.questions) {
      const key = (q.type || '').trim() || '未分类'
      if (!groups[key]) groups[key] = []
      groups[key].push(q)
    }
    return groups
  }, [paper])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !paper) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <div className="h-16 w-16 bg-muted rounded-full flex items-center justify-center mb-4">
          <FileText className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-medium mb-2">试卷不存在</h3>
        <p className="text-muted-foreground mb-6">加载失败或已被删除</p>
        <Button asChild variant="outline">
          <Link to="/papers">返回列表</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-background">
      <div className="border-b border-border p-4 flex items-center justify-between sticky top-0 bg-background/80 backdrop-blur-sm z-10 print:hidden">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild className="rounded-full">
            <Link to="/papers">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div className="hidden sm:block">
            <h1 className="font-semibold text-sm">试卷详情</h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handlePrint}>
            <Printer className="h-4 w-4 mr-2" />
            打印
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => paperId && loadDownloadLinks(paperId)}
            disabled={!paperId || isLoadingLinks}
          >
            {isLoadingLinks ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Link2 className="h-4 w-4 mr-2" />
            )}
            获取链接
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="max-w-4xl mx-auto p-8 print:p-0">
          <div className="text-center mb-8 print:mb-6">
            <div className="inline-flex items-center justify-center h-16 w-16 rounded-2xl bg-primary/10 text-primary mb-6 print:hidden">
              <FileText className="h-8 w-8" />
            </div>
            <h1 className="text-3xl font-bold tracking-tight mb-4 text-foreground">{paper.name}</h1>

            <div className="flex flex-wrap items-center justify-center gap-3 text-sm text-muted-foreground">
              <Badge variant="secondary" className="px-3 py-1 text-sm font-normal">试卷 #{paper.id}</Badge>
              <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
              <span>{paper.questions.length} 道题</span>
              <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
              <span>{formatDate(paper.createdAt)}</span>
            </div>
          </div>

          {paper.analysis && (
            <div className="mb-8 p-4 rounded-xl bg-muted/30 border border-border/50 print:hidden">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 font-semibold">
                  <BarChart3 className="h-4 w-4 text-primary" />
                  AI 智能分析
                </div>
                <Badge variant="outline" className="bg-background">
                  难度系数 {Number.isFinite(paper.analysis.difficultyScore) ? paper.analysis.difficultyScore.toFixed(2) : '--'}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground leading-6">
                {paper.analysis.aiComment || "暂无详细评语"}
              </p>
            </div>
          )}

          <Separator className="my-8 print:hidden" />

          {Object.keys(questionsByType).length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <p>暂无题目</p>
            </div>
          ) : (
            Object.entries(questionsByType).map(([type, questions], typeIndex) => (
              <div key={type} className="mb-8">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground text-sm font-medium">
                    {typeIndex + 1}
                  </span>
                  {type}
                  <span className="text-sm font-normal text-muted-foreground">
                    (共 {questions.length} 题)
                  </span>
                </h2>

                <div className="space-y-4 pl-2 border-l-2 border-border/50 ml-3.5">
                  {questions.map((question, index) => (
                    <div
                      key={`${question.questionId}-${index}`}
                      className="group relative pl-6 py-2"
                    >
                      <div className="absolute left-[-5px] top-5 h-2.5 w-2.5 rounded-full border-2 border-background bg-muted-foreground/30 group-hover:bg-primary transition-colors" />

                      <div className="rounded-lg border border-border bg-card p-4 transition-all hover:shadow-sm">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="font-mono text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                #{question.questionId}
                              </span>
                              <div className="flex gap-1.5">
                                {!!question.difficulty && (
                                  <Badge variant="outline" className="text-[10px] h-5">{question.difficulty}</Badge>
                                )}
                                {!!question.knowledgePoint && (
                                  <Badge variant="outline" className="text-[10px] h-5">
                                    {question.knowledgePoint}
                                  </Badge>
                                )}
                              </div>
                            </div>
                          </div>

                          {question.sourceUrl ? (
                            <Button variant="ghost" size="sm" asChild className="h-8">
                              <a
                                href={question.sourceUrl}
                                target="_blank"
                                rel="noreferrer"
                              >
                                <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
                                原题
                              </a>
                            </Button>
                          ) : (
                            <span className="text-[10px] text-muted-foreground/50 select-none">无链接</span>
                          )}
                        </div>

                        {!!question.stem && (
                          <details className="mt-3">
                            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground select-none">
                              查看题干
                            </summary>
                            <div className="mt-2 max-h-60 overflow-auto rounded-md bg-muted/30 border border-border/60 p-3 text-sm whitespace-pre-wrap leading-6">
                              {question.stem}
                            </div>
                          </details>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}

          {!!download?.success && (
            <>
              <Separator className="my-8" />
              <Card className="print:border-0 print:shadow-none bg-muted/30">
                <CardContent className="p-6">
                  <div className="font-semibold mb-4 flex items-center gap-2">
                    <Link2 className="h-4 w-4" />
                    查看链接
                  </div>

                  {!!download.instructions?.length && (
                    <ol className="list-decimal pl-5 space-y-1 text-sm text-muted-foreground mb-4">
                      {download.instructions.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ol>
                  )}

                  {download.questionLinks?.length ? (
                    <div className="grid gap-2">
                      {download.questionLinks.map((url, i) => (
                        <a
                          key={`${url}-${i}`}
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-sm text-primary hover:underline break-all block p-2 rounded hover:bg-background transition-colors"
                        >
                          {i + 1}. {url}
                        </a>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      暂无链接
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
